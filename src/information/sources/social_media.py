"""社交媒体适配器 — last30days-cn 封装。

覆盖平台：微博、小红书、B站、知乎、抖音、微信公众号、百度搜索、今日头条

使用方式：
    Claude Code 上下文: 通过 Skill 工具调用 last30days-cn
    Python 测试/离线: 使用 mock 数据

设计说明：
    此适配器定义采集接口。实际数据采集由 Claude Code orchestrator
    调用 `Skill(last30days-cn)` 完成。Python 层面提供数据模型和
    后处理逻辑（情感分析、实体提取等）。
"""

from __future__ import annotations

import re
from datetime import datetime

from src.information.schema import (
    EventCategory,
    ProcessedItem,
    RawItem,
    SentimentResult,
    SourceType,
    Topic,
)
from src.information.sources.base import InformationSource, SourceMeta


class SocialMediaSource(InformationSource):
    """中国社交媒体聚合适配器。

    通过 last30days-cn skill 统一查询 8 大平台。
    零配置即可使用 B站/知乎/百度/今日头条。
    配置 API key 可解锁更多平台。
    """

    meta = SourceMeta(
        source_type=SourceType.SOCIAL_MEDIA,
        platform="last30days-cn",
        label="中国社交媒体聚合",
        description="微博/小红书/B站/知乎/抖音/微信公众号/百度/头条 8 平台",
        requires_auth=False,
        rate_limit_per_minute=10,
        default_days_back=7,
        max_days_back=30,
        credibility=0.3,  # 社交媒体可信度权重
    )

    # 平台列表（从 last30days-cn 文档）
    PLATFORMS = [
        "weibo",
        "xiaohongshu",
        "bilibili",
        "zhihu",
        "douyin",
        "wechat",
        "baidu",
        "toutiao",
    ]

    # 情感关键词词典（简化版，Phase 3 升级为 LLM 驱动）
    _POSITIVE_WORDS = {
        "利好", "突破", "超预期", "增长", "看好", "机会", "爆发", "加速",
        "放量", "涨停", "龙头", "受益", "景气", "反转", "底部", "低估",
        "国产替代", "自主可控", "政策支持", "需求暴增", "技术突破",
    }
    _NEGATIVE_WORDS = {
        "利空", "暴跌", "亏损", "下滑", "减持", "退市", "暴雷", "踩雷",
        "见顶", "泡沫", "过剩", "监管", "调查", "处罚", "诉讼", "违约",
        "制裁", "断供", "封锁", "限制", "产能过剩", "需求萎缩",
    }

    async def search(self, topic: Topic, days_back: int | None = None) -> list[RawItem]:
        """通过 last30days-cn skill 搜索。

        注意：此方法在纯 Python 运行时返回空列表。
        实际采集由 Claude Code orchestrator 调用 Skill(last30days-cn) 完成。
        orchestrator 将采集结果转换为 RawItem 列表后传入 get_sentiment()。
        """
        # 生成查询字符串（供 orchestrator 使用）
        return []

    async def get_sentiment(self, items: list[RawItem]) -> SentimentResult:
        """基于关键词词典的情感分析（快速，不需要 LLM）。"""
        if not items:
            return SentimentResult(
                source_type=self.meta.source_type,
                platform=self.meta.platform,
                items_count=0,
            )

        processed: list[ProcessedItem] = []
        bullish = bearish = neutral = 0
        scores: list[float] = []

        for item in items:
            score = self._keyword_sentiment(item.title + " " + item.content)
            scores.append(score)
            if score > 0.15:
                bullish += 1
            elif score < -0.15:
                bearish += 1
            else:
                neutral += 1

            processed.append(
                ProcessedItem(
                    source_item=item,
                    sentiment_score=score,
                    sentiment_confidence=0.6,  # 关键词方法置信度中等
                    extracted_entities=self._extract_stock_codes(item.content),
                    event_category=self._classify_event(score),
                    keywords=list(self._extract_keywords(item.title + " " + item.content)),
                )
            )

        n = len(scores)
        mean_score = sum(scores) / n if n else 0.0
        variance = sum((s - mean_score) ** 2 for s in scores) / n if n > 1 else 0.0

        return SentimentResult(
            source_type=self.meta.source_type,
            platform=self.meta.platform,
            items_count=n,
            sentiment_mean=round(mean_score, 3),
            sentiment_std=round(variance ** 0.5, 3),
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            processed_items=processed,
        )

    # ── 关键词情感分析 ─────────────────────────────────────────────────────

    def _keyword_sentiment(self, text: str) -> float:
        """基于关键词计数计算情感分（-1 ~ 1）。"""
        pos = sum(1 for w in self._POSITIVE_WORDS if w in text)
        neg = sum(1 for w in self._NEGATIVE_WORDS if w in text)
        total = pos + neg
        if total == 0:
            return 0.0
        raw = (pos - neg) / max(total, 1)
        return max(-1.0, min(1.0, raw * 0.7))  # 压缩到 ±0.7（保守）

    @staticmethod
    def _extract_stock_codes(text: str) -> list[str]:
        """从文本中提取 A 股代码（6 位数字）。"""
        codes = re.findall(r"\b(00[0-9]{4}|30[0-9]{4}|60[0-9]{4}|68[0-9]{4})\b", text)
        return list(set(codes))

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """简单 TF 关键词提取（Phase 3 升级为 jieba + TF-IDF）。"""
        # 去停用词
        stopwords = {
            "的", "了", "是", "在", "和", "也", "都", "就", "这", "那",
            "一个", "没有", "我们", "他们", "它们", "这个", "那个", "可以",
            "已经", "因为", "所以", "但是", "如果", "虽然", "还是", "只是",
        }
        words = re.findall(r"[一-鿿]{2,}", text)
        return {w for w in words if w not in stopwords}  # 返回所有非停用词的 2+ 字词

    @staticmethod
    def _classify_event(score: float) -> EventCategory:
        if score > 0.3:
            return EventCategory.POSITIVE_SHORT
        elif score < -0.3:
            return EventCategory.NEGATIVE_SHORT
        return EventCategory.NEUTRAL


# ── 平台特定子类（可覆盖可信度） ──────────────────────────────────────────────


class WeiboSource(SocialMediaSource):
    """微博适配器。需要 WEIBO_ACCESS_TOKEN（可选，提升采集质量）。"""

    meta = SourceMeta(
        source_type=SourceType.SOCIAL_MEDIA,
        platform="weibo",
        label="微博",
        description="微博热搜/话题/帖子",
        requires_auth=False,
        credibility=0.3,
    )


class ZhihuSource(SocialMediaSource):
    """知乎适配器。可配置 ZHIHU_COOKIE 提升采集质量。"""

    meta = SourceMeta(
        source_type=SourceType.SOCIAL_MEDIA,
        platform="zhihu",
        label="知乎",
        description="知乎问答/文章/专栏",
        requires_auth=False,
        credibility=0.4,  # 知乎内容质量略高于微博
    )


class BilibiliSource(SocialMediaSource):
    """B站适配器。免费可直接使用。"""

    meta = SourceMeta(
        source_type=SourceType.SOCIAL_MEDIA,
        platform="bilibili",
        label="B站",
        description="B站视频/专栏/动态",
        requires_auth=False,
        credibility=0.35,
    )
