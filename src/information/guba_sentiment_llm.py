# -*- coding: utf-8 -*-
"""股吧/微博情绪 LLM 分析 — 预取注入防编造。

借鉴 TradingAgents `sentiment_analyst` 的反幻觉设计 (issue #557/#796):
  - **预取注入**: 先拉取股吧热帖(标题/互动/多空标记)与可选的外部社交源(微博等),
    以 `<start_of_*>/<end_of_*>` 结构化块注入 prompt。
  - **禁编造**: prompt 明确要求 LLM 只能分析注入的数据, 禁止编造/补充帖子内容。
  - **结构化输出**: 用 `src/llm/structured.invoke_structured_or_freetext` 输出
    确定性情绪报告 (band/score/confidence/narrative), provider 不支持时降级。

数据源:
  - 股吧: `GubaProvider` (东财官方论坛, T1, 置信度 0.80)
  - 微博等: 由 orchestrator 通过 last30days-cn 采集后作为 `extra_sources` 传入

Usage:
    from src.information.guba_sentiment_llm import GubaSentimentLLMAnalyzer

    result = GubaSentimentLLMAnalyzer().analyze("600519")
    # → {overall_band, overall_score, confidence, narrative, ...}
    #   失败时带 data_gap=True + fallback 字段, 不抛异常
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.data.guba_provider import GubaProvider, GubaSentiment
from src.data.source_citation import (
    NATURE_INTERPRETATION,
    SOURCE_TIER_T1,
    SourceCitation,
    make_citation,
)
from src.llm.structured import dataclass_to_json_schema, invoke_structured_or_freetext

logger = logging.getLogger(__name__)

# 情绪带 (与 TradingAgents SentimentBand 对齐)
SENTIMENT_BANDS = [
    "Bullish", "Mildly Bullish", "Neutral", "Mixed",
    "Mildly Bearish", "Bearish",
]


@dataclass
class GubaLLMSentiment:
    """LLM 情绪分析结构化输出 (置信度分制 0.0-1.0, 与全局护栏统一)。"""

    overall_band: str  # Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish
    overall_score: float  # 0-10, 5=中性
    confidence: float  # 0.0-1.0
    narrative: str  # 逐源分析 + 分歧 + 主导叙事


@dataclass
class GubaSentimentResult:
    """股吧/微博 LLM 情绪分析结果 DTO (跨层数据用 dataclass, 不用裸 dict)。"""

    symbol: str
    overall_band: str = "Neutral"
    overall_score: float = 5.0
    confidence: float = 0.0  # 0.0-1.0
    narrative: str = ""
    source: str = "guba_llm"
    data_gap: bool = False
    reason: str = ""
    fallback_text: str = ""
    citation: Optional[SourceCitation] = None

    def is_gap(self) -> bool:
        return self.data_gap


_SCHEMA = dataclass_to_json_schema(GubaLLMSentiment)
_SCHEMA["properties"]["overall_band"]["enum"] = SENTIMENT_BANDS
_SCHEMA["properties"]["confidence"] = {"type": "number"}


def _render_guba_block(sentiment: GubaSentiment) -> str:
    """把股吧情绪快照渲染成结构化注入块。"""
    lines = [
        f"股票: {sentiment.symbol}",
        f"帖子数: {sentiment.post_count} | 总点击: {sentiment.total_clicks} "
        f"| 总评论: {sentiment.total_comments} | 帖均互动: {sentiment.engagement_per_post}",
        f"多空标记: 看多 {sentiment.bullish_count} / 看空 {sentiment.bearish_count} "
        f"(无标记 {max(0, sentiment.post_count - sentiment.bullish_count - sentiment.bearish_count)})",
    ]
    if sentiment.bull_bear_ratio is not None:
        lines.append(f"多空比: {sentiment.bull_bear_ratio:.2f}")
    lines.append(f"热度分: {sentiment.heat_score}/100")
    if sentiment.hot_titles:
        lines.append("Top 热帖标题:")
        for i, title in enumerate(sentiment.hot_titles[:10], 1):
            lines.append(f"  {i}. {title}")
    return "\n".join(lines)


def _render_extra_block(items: list[dict]) -> str:
    """渲染外部社交源(微博等)条目块。每条含 title/content/engagement 可选。"""
    lines = []
    for i, item in enumerate(items[:30], 1):
        title = str(item.get("title") or "")[:80]
        content = str(item.get("content") or item.get("text") or "")[:200]
        engagement = item.get("engagement") or item.get("likes") or item.get("comments") or ""
        tag = item.get("sentiment_tag") or ""
        tag_suffix = f" [标签:{tag}]" if tag else ""
        line = f"  {i}. {title}{tag_suffix}"
        if content:
            line += f" — {content}"
        if engagement:
            line += f" (互动:{engagement})"
        lines.append(line)
    return "\n".join(lines) if lines else "(无外部社交条目)"


class GubaSentimentLLMAnalyzer:
    """股吧情绪 LLM 分析器 (预取注入 + 结构化输出)。"""

    def __init__(self, model: str = "deepseek-chat", guba_provider: Optional[GubaProvider] = None):
        self.model = model
        self._guba = guba_provider or GubaProvider()

    def analyze(
        self,
        symbol: str,
        name: str = "",
        extra_sources: Optional[list[dict]] = None,
    ) -> GubaSentimentResult:
        """分析指定股票股吧/微博情绪。

        Args:
            symbol: 6 位股票代码。
            name: 股票名称。
            extra_sources: 可选外部社交源条目(如微博), 每条含
                {title, content, engagement, sentiment_tag} 任一字段。

        Returns:
            GubaSentimentResult DTO; 降级/失败时 data_gap=True, 不抛异常。
        """
        guba = self._guba.fetch_sentiment(symbol)
        extra = extra_sources or []
        citation = None

        if guba is None:
            if not extra:
                return GubaSentimentResult(
                    symbol=symbol,
                    data_gap=True,
                    reason="股吧数据不可用且无外部社交源",
                )
            guba_block = "(股吧数据不可用)"
        else:
            guba_block = _render_guba_block(guba)
            citation = getattr(guba, "citation", None)

        prompt = _build_prompt(
            symbol=symbol,
            name=name,
            guba_block=guba_block,
            extra_block=_render_extra_block(extra),
        )
        system = (
            "你是 A 股个股情绪分析师。只能基于下方注入的数据分析，"
            "**禁止编造或补充任何帖子内容**；数据不足时在 confidence 与 narrative 中如实说明。"
            "输出 JSON 对象: overall_band(枚举) / overall_score(0-10 数值) / "
            "confidence(0.0-1.0 数值) / narrative(字符串)。"
        )

        result = invoke_structured_or_freetext(
            prompt,
            schema=_SCHEMA,
            model=self.model,
            system=system,
        )

        if isinstance(result, str):
            return GubaSentimentResult(
                symbol=symbol,
                data_gap=True,
                reason="结构化输出两条路径均未达标",
                fallback_text=(result or "")[:500],
                citation=citation,
            )

        # 置信度分制统一: LLM 输出 0-1; 极端越界钳制
        conf = float(result.get("confidence", 0.0) or 0.0)
        conf = max(0.0, min(1.0, conf))
        return GubaSentimentResult(
            symbol=symbol,
            overall_band=result.get("overall_band", "Neutral"),
            overall_score=float(result.get("overall_score", 5.0) or 5.0),
            confidence=conf,
            narrative=str(result.get("narrative", "")),
            citation=citation or _make_citation(symbol),
        )


def _make_citation(symbol: str) -> SourceCitation:
    """构造股吧 LLM 情绪的溯源引用 (T1, interpretation)。"""
    return make_citation(
        provider="guba",
        field="guba_llm_sentiment",
        data_type="topic_policy",
        url=f"https://guba.eastmoney.com/list,{symbol}.html",
        source_tier=SOURCE_TIER_T1,
        nature=NATURE_INTERPRETATION,
        confidence=0.80,
    )


def _build_prompt(symbol: str, name: str, guba_block: str, extra_block: str) -> str:
    """组装预取注入 prompt (模块级函数)。"""
    return (
        f"请对 {name or symbol} ({symbol}) 做情绪综合分析。\n\n"
        f"## 股吧数据 (已预取, 东财官方论坛)\n"
        f"<start_of_guba>\n{guba_block}\n<end_of_guba>\n\n"
        f"## 外部社交源 (微博等, 已预取)\n"
        f"<start_of_social>\n{extra_block}\n<end_of_social>\n\n"
        "## 分析要点\n"
        "1. 多空标记与互动热度: 高互动帖子权重更高; 样本量小要降 confidence。\n"
        "2. 看多/看空标题的叙事主题: 反复出现的主题即主导叙事。\n"
        "3. 数据局限: 若某来源无数据或样本过少, 明确说明, 不要脑补。\n"
        "4. 情绪只是信号之一, 不作为价格预测。"
    )
