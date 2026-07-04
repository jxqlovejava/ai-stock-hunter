"""财经新闻适配器 — AKShare news 模块封装。

覆盖：个股公告、财经新闻、行业快讯

Ref: AKShare 文档 — ak.news_stock_notices(), ak.news_finance_news()
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


class FinancialNewsSource(InformationSource):
    """AKShare 财经新闻适配器。

    免费、全量、可回测（AKShare 返回 DataFrame）。
    覆盖：个股公告、财经新闻、行业快讯。
    """

    meta = SourceMeta(
        source_type=SourceType.FINANCIAL_NEWS,
        platform="akshare",
        label="AKShare 财经新闻",
        description="A股公告/财经新闻/行业快讯",
        requires_auth=False,
        rate_limit_per_minute=30,
        default_days_back=7,
        max_days_back=90,
        credibility=0.6,  # 财经媒体可信度
    )

    # 情感关键词（财经新闻语境）
    _POSITIVE_WORDS = {
        "净利润增长", "营收增长", "中标", "签约", "获批", "扩产",
        "回购", "增持", "分红", "送转", "业绩预增", "扭亏为盈",
        "订单饱满", "产能利用率", "技术突破", "市场份额提升",
    }
    _NEGATIVE_WORDS = {
        "净利润下降", "亏损", "业绩预减", "减持", "质押", "冻结",
        "立案调查", "行政处罚", "退市风险", "债务违约", "商誉减值",
        "停产", "限产", "原材料涨价", "竞争加剧", "下游需求疲软",
    }

    async def search(self, topic: Topic, days_back: int | None = None) -> list[RawItem]:
        """通过 AKShare 搜索财经新闻。

        注意：此方法在纯 Python 运行时返回空列表。
        实际采集由 Claude Code orchestrator 通过 AKShare Python 库完成。
        orchestrator 将结果转换为 RawItem 列表后传入 get_sentiment()。

        生产环境使用方式：
            import akshare as ak
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily")
        """
        return []

    async def get_sentiment(self, items: list[RawItem]) -> SentimentResult:
        """财经新闻情感分析。"""
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
            score = self._finance_sentiment(item.title + " " + item.content)
            scores.append(score)
            if score > 0.1:
                bullish += 1
            elif score < -0.1:
                bearish += 1
            else:
                neutral += 1

            processed.append(
                ProcessedItem(
                    source_item=item,
                    sentiment_score=score,
                    sentiment_confidence=0.7,  # 财经新闻比社交媒体可信
                    extracted_entities=self._extract_codes(item.title + " " + item.content),
                    event_category=self._classify_event(score),
                    keywords=self._extract_keywords(item.title),
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

    def _finance_sentiment(self, text: str) -> float:
        """财经新闻情感分析（关键词法）。"""
        pos = sum(1 for w in self._POSITIVE_WORDS if w in text)
        neg = sum(1 for w in self._NEGATIVE_WORDS if w in text)
        total = pos + neg
        if total == 0:
            # 检查是否有数值增长/下降描述
            if re.search(r"(增长|上升|提高|扩大)\d+%", text):
                return 0.3
            if re.search(r"(下降|减少|降低|缩小)\d+%", text):
                return -0.3
            return 0.0
        raw = (pos - neg) / max(total, 1)
        return max(-1.0, min(1.0, raw * 0.8))

    @staticmethod
    def _extract_codes(text: str) -> list[str]:
        """提取 A 股代码。"""
        codes = re.findall(r"\b(00[0-9]{4}|30[0-9]{4}|60[0-9]{4}|68[0-9]{4})\b", text)
        return list(set(codes))

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """从标题提取关键短语。"""
        # 提取引号中的内容 + 前 3 个实体词
        quoted = re.findall(r"[「「]([^」」]+)[」」]", text)
        if quoted:
            return quoted[:5]
        # 简单分词（取 2-4 字词）
        words = re.findall(r"[一-鿿]{2,4}", text)
        stopwords = {"的", "了", "是", "在", "和", "也", "都", "就", "这", "那", "公告", "关于"}
        return [w for w in words if w not in stopwords][:5]

    @staticmethod
    def _classify_event(score: float) -> EventCategory:
        if score > 0.5:
            return EventCategory.POSITIVE_MEDIUM
        elif score > 0.1:
            return EventCategory.POSITIVE_SHORT
        elif score < -0.5:
            return EventCategory.NEGATIVE_MEDIUM
        elif score < -0.1:
            return EventCategory.NEGATIVE_SHORT
        return EventCategory.NEUTRAL
