"""NLP 处理管道 — 情感分析 + 实体识别 + 事件分类。

两套实现：
- ClaudeNLPProcessor: 基于 Claude LLM（高质量，需要 API）
- KeywordNLPProcessor: 基于关键词词典（快速，离线可用）

Ref: OpenStock 源对齐分类器 (spread 分类器)
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from src.information.schema import (
    EventCategory,
    ProcessedItem,
    RawItem,
    SentimentResult,
    SourceAlignment,
    SourceType,
)


class NLPProcessor(ABC):
    """NLP 处理器抽象基类。"""

    @abstractmethod
    async def analyze_item(self, item: RawItem, topic_context: str = "") -> ProcessedItem:
        """对单条原始条目做 NLP 分析。"""
        ...

    async def analyze_batch(
        self, items: list[RawItem], topic_context: str = ""
    ) -> list[ProcessedItem]:
        """批量分析（默认串行，子类可覆盖为并行）。"""
        results = []
        for item in items:
            results.append(await self.analyze_item(item, topic_context))
        return results


class KeywordNLPProcessor(NLPProcessor):
    """基于关键词词典的快速 NLP 处理器。

    优点：零延迟、零成本、可离线
    缺点：准确率低于 LLM（约 60-70%）
    """

    # 正面/负面关键词
    POSITIVE = {
        "利好", "突破", "超预期", "增长", "看好", "机会", "爆发", "加速",
        "放量", "涨停", "龙头", "受益", "景气", "反转", "底部", "低估",
        "国产替代", "自主可控", "政策支持", "需求暴增", "技术突破",
        "回购", "增持", "分红", "中标", "签约", "获批", "扩产",
    }
    NEGATIVE = {
        "利空", "暴跌", "亏损", "下滑", "减持", "退市", "暴雷", "踩雷",
        "见顶", "泡沫", "过剩", "监管", "调查", "处罚", "诉讼", "违约",
        "制裁", "断供", "封锁", "限制", "产能过剩", "需求萎缩",
        "立案调查", "行政处罚", "商誉减值", "债务违约",
    }

    async def analyze_item(self, item: RawItem, topic_context: str = "") -> ProcessedItem:
        """关键词情感分析 + 实体提取。"""
        text = f"{item.title} {item.content}"
        score = self._sentiment_score(text)
        entities = self._extract_entities(text)
        event = self._classify_event(score, text)
        keywords = self._extract_keywords(text)

        return ProcessedItem(
            source_item=item,
            sentiment_score=score,
            sentiment_confidence=0.6,
            extracted_entities=entities,
            event_category=event,
            keywords=list(keywords)[:10],
            summary=item.title[:200],
            relevance_score=self._relevance(text, topic_context),
        )

    def _sentiment_score(self, text: str) -> float:
        pos = sum(1 for w in self.POSITIVE if w in text)
        neg = sum(1 for w in self.NEGATIVE if w in text)
        total = pos + neg
        if total == 0:
            return 0.0
        return max(-1.0, min(1.0, (pos - neg) / total * 0.7))

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """提取股票代码 + 公司名 + 关键人物。"""
        entities: list[str] = []

        # A 股代码
        codes = re.findall(r"\b(00[0-9]{4}|30[0-9]{4}|60[0-9]{4}|68[0-9]{4})\b", text)
        entities.extend(codes)

        # 公司名（简单规则：以"公司/集团/股份/科技/电子/半导体"等结尾的 2-6 字词）
        companies = re.findall(
            r"([一-鿿]{2,6}(?:公司|集团|股份|科技|电子|半导体|芯片|光刻|封测|存储|算力|通信))",
            text,
        )
        entities.extend(companies)

        return list(set(entities))

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """提取关键词（2-4 字词，去停用词）。"""
        stopwords = {
            "的", "了", "是", "在", "和", "也", "都", "就", "这", "那",
            "一个", "没有", "我们", "他们", "这个", "那个", "可以", "已经",
            "因为", "所以", "但是", "如果", "虽然", "还是", "只是",
            "今天", "昨天", "明天", "目前", "现在", "今年", "去年",
            "什么", "怎么", "为什么", "怎么样", "如何", "哪", "吗",
        }
        words = re.findall(r"[一-鿿a-zA-Z]{2,4}", text)
        return {w for w in words if w not in stopwords}

    @staticmethod
    def _classify_event(score: float, text: str) -> EventCategory:
        """基于情感分和文本内容分类事件。"""
        # 长期性关键词
        long_term = {"国产替代", "自主可控", "技术突破", "产业升级", "战略转型", "碳中和"}
        if any(w in text for w in long_term):
            return EventCategory.POSITIVE_LONG if score > 0 else EventCategory.NEUTRAL

        if score > 0.5:
            return EventCategory.POSITIVE_MEDIUM
        elif score > 0.1:
            return EventCategory.POSITIVE_SHORT
        elif score < -0.5:
            return EventCategory.NEGATIVE_MEDIUM
        elif score < -0.1:
            return EventCategory.NEGATIVE_SHORT
        return EventCategory.NEUTRAL

    @staticmethod
    def _relevance(text: str, topic_context: str) -> float:
        """基于关键词重叠计算与主题的相关度。"""
        if not topic_context:
            return 0.5
        topic_words = set(re.findall(r"[一-鿿a-zA-Z]{2,}", topic_context.lower()))
        text_words = set(re.findall(r"[一-鿿a-zA-Z]{2,}", text.lower()))
        if not topic_words:
            return 0.5
        overlap = topic_words & text_words
        return min(1.0, len(overlap) / max(len(topic_words), 1))


class ClaudeNLPProcessor(NLPProcessor):
    """基于 Claude LLM 的 NLP 处理器。

    高质量情感分析 + 实体识别 + 摘要生成。
    由 Claude Code orchestrator 调用（通过 Skill 工具或直接 prompt）。

    在纯 Python 运行时，此处理器返回基于关键词的降级结果。
    """

    def __init__(self) -> None:
        self._fallback = KeywordNLPProcessor()

    async def analyze_item(self, item: RawItem, topic_context: str = "") -> ProcessedItem:
        """使用 Claude 分析单条信息。

        注意：纯 Python 运行时会降级为关键词方法。
        生产环境中由 Claude Code orchestrator 注入 LLM 分析结果。
        """
        # 检查是否有预计算的分析结果（由 orchestrator 注入）
        if "llm_sentiment" in item.metadata:
            return ProcessedItem(
                source_item=item,
                sentiment_score=item.metadata["llm_sentiment"],
                sentiment_confidence=item.metadata.get("llm_confidence", 0.75),
                extracted_entities=item.metadata.get("llm_entities", []),
                event_category=self._parse_event(item.metadata.get("llm_event", "neutral")),
                keywords=item.metadata.get("llm_keywords", []),
                summary=item.metadata.get("llm_summary", ""),
                relevance_score=item.metadata.get("llm_relevance", 0.5),
            )

        # 降级：关键词方法
        return await self._fallback.analyze_item(item, topic_context)

    async def analyze_batch(
        self, items: list[RawItem], topic_context: str = ""
    ) -> list[ProcessedItem]:
        """批量分析（Claude 可单次处理多条）。"""
        # 如果有预计算结果，直接返回
        if all("llm_sentiment" in item.metadata for item in items):
            results = []
            for item in items:
                results.append(await self.analyze_item(item, topic_context))
            return results

        # 降级
        return await self._fallback.analyze_batch(items, topic_context)

    @staticmethod
    def _parse_event(event_str: str) -> EventCategory:
        mapping = {
            "positive_short": EventCategory.POSITIVE_SHORT,
            "positive_medium": EventCategory.POSITIVE_MEDIUM,
            "positive_long": EventCategory.POSITIVE_LONG,
            "negative_short": EventCategory.NEGATIVE_SHORT,
            "negative_medium": EventCategory.NEGATIVE_MEDIUM,
            "negative_long": EventCategory.NEGATIVE_LONG,
            "neutral": EventCategory.NEUTRAL,
            "unknown": EventCategory.UNKNOWN,
        }
        return mapping.get(event_str, EventCategory.UNKNOWN)

    @staticmethod
    def build_analysis_prompt(items: list[RawItem], topic_name: str) -> str:
        """构建 LLM 分析 prompt（供 orchestrator 使用）。

        输出格式为 JSON，每条包含 sentiment/entities/event/summary。
        """
        items_text = ""
        for i, item in enumerate(items[:20]):  # 限制 20 条
            items_text += f"""
[{i+1}] 标题: {item.title}
    内容: {item.content[:300]}
    来源: {item.platform} ({item.source_type.value})
"""
        return f"""分析以下关于「{topic_name}」的信息条目。对每条输出 JSON：

{{
  "analyses": [
    {{
      "index": 1,
      "sentiment": -1.0到1.0之间的浮点数（-1强烈看空,0中性,1强烈看多）,
      "sentiment_confidence": 0.0到1.0（判断置信度）,
      "entities": ["提取的股票代码/公司名/关键人物"],
      "event_category": "positive_short/positive_medium/positive_long/negative_short/negative_medium/negative_long/neutral/unknown",
      "keywords": ["关键词"],
      "summary": "1-2句话摘要",
      "relevance": 0.0到1.0（与主题的相关度）
    }}
  ]
}}

{items_text}"""


# ── 管道函数 ──────────────────────────────────────────────────────────────────


async def process_items(
    items: list[RawItem],
    topic_context: str = "",
    *,
    use_llm: bool = False,
) -> list[ProcessedItem]:
    """便捷函数：批量处理原始条目。"""
    processor = ClaudeNLPProcessor() if use_llm else KeywordNLPProcessor()
    return await processor.analyze_batch(items, topic_context)


def compute_source_alignment(
    sentiment_results: list[SentimentResult],
) -> SourceAlignment:
    """计算跨源对齐度。

    Ref: OpenStock getSourceAlignment() — spread 分类器
    - spread ≤ 12 → ALIGNED
    - spread ≥ 25 → DIVERGENT
    - otherwise → MIXED

    我们将 sentiment_mean 映射到 0-100 标度：
    spread = max(sentiment_means) - min(sentiment_means) * 100
    """
    valid = [sr for sr in sentiment_results if sr.items_count > 0]
    if len(valid) == 0:
        return SourceAlignment.NO_DATA
    if len(valid) == 1:
        return SourceAlignment.SINGLE_SOURCE

    means = [(sr.sentiment_mean + 1) * 50 for sr in valid]  # 映射到 0-100
    spread = max(means) - min(means)

    if spread <= 12:
        return SourceAlignment.ALIGNED
    elif spread >= 25:
        return SourceAlignment.DIVERGENT
    return SourceAlignment.MIXED
