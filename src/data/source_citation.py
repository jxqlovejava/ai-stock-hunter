# -*- coding: utf-8 -*-
"""统一数据溯源 — 所有分析输出必须携带 SourceCitation。

Phase 1: 护栏体系基础数据类型。
Phase 1+: 引入 T0-T3 信源分级与数据缺口标记。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


# T0-T3 信源分级
# T0: 原始一手官方数据（交易所、央行、公司公告、巨潮）
# T1: 权威数据商直接整理（券商官方、国信、mootdx、同花顺 iFinD、东方财富 datacenter）
# T2: 聚合/爬虫/二次加工（akshare、腾讯、聚合 API、模型解释、财经媒体）
# T3: 推测/三手/未验证（LLM 推导、自媒体、传闻、观点）
SOURCE_TIER_T0 = "T0"
SOURCE_TIER_T1 = "T1"
SOURCE_TIER_T2 = "T2"
SOURCE_TIER_T3 = "T3"

# 数据性质：事实 / 解释 / 推测
NATURE_FACT = "fact"
NATURE_INTERPRETATION = "interpretation"
NATURE_SPECULATION = "speculation"
NATURE_DATA_GAP = "data_gap"


@dataclass
class SourceCitation:
    """数据来源引用 — 每条分析数据点的溯源信息。"""

    provider: str  # 数据源标识: "guosen" / "mootdx" / "akshare" / "tencent" / "huatai" / "eastmoney"
    field: str  # 数据字段名, 如 "pe_ttm" / "close_price"
    fetch_timestamp: datetime = field(default_factory=datetime.now)
    data_freshness: timedelta = field(default_factory=lambda: timedelta(hours=1))
    confidence: float = 0.7  # 来源置信度 0.0-1.0
    url_or_endpoint: str = ""  # 可选, 用于审计回溯
    is_cached: bool = False
    # Phase 1+: T0-T3 信源分级
    source_tier: str = SOURCE_TIER_T2  # T0 / T1 / T2 / T3
    nature: str = NATURE_FACT          # fact / interpretation / speculation / data_gap

    @property
    def is_fresh(self) -> bool:
        """数据是否仍未过期。"""
        freshness = self.data_freshness if isinstance(self.data_freshness, timedelta) else timedelta(seconds=int(self.data_freshness))
        return datetime.now() - self.fetch_timestamp <= freshness

    @property
    def age(self) -> timedelta:
        """数据已存在时长。"""
        return datetime.now() - self.fetch_timestamp

    @property
    def is_t1_or_above(self) -> bool:
        """是否为 T1+ 信源（可用于军规 r022 交叉验证）。"""
        return self.source_tier in (SOURCE_TIER_T0, SOURCE_TIER_T1)

    @property
    def is_data_gap(self) -> bool:
        """是否为数据缺口标记。"""
        return self.nature == NATURE_DATA_GAP

    @property
    def quality_score(self) -> float:
        """综合数据质量得分（0.0-1.0）。"""
        if self.nature == NATURE_DATA_GAP:
            return 0.0
        score = self.confidence
        if self.source_tier == SOURCE_TIER_T0:
            score = min(1.0, score * 1.15)
        elif self.source_tier == SOURCE_TIER_T1:
            score = min(1.0, score * 1.05)
        elif self.source_tier == SOURCE_TIER_T3:
            score *= 0.70
        if self.nature == NATURE_INTERPRETATION:
            score *= 0.90
        elif self.nature == NATURE_SPECULATION:
            score *= 0.40
        if not self.is_fresh:
            score *= 0.70
        return round(max(0.0, min(1.0, score)), 4)


# 数据源基准置信度
PROVIDER_CONFIDENCE: dict[str, float] = {
    "guosen": 0.90,
    "mootdx": 0.85,
    "eastmoney": 0.80,
    "huatai": 0.80,
    "tencent": 0.75,
    "akshare": 0.70,
    "cninfo": 0.90,
    "tonghuashun": 0.80,
    "manual": 0.95,
    "llm_derived": 0.40,
    "miaoxiang-data-executive": 0.80,
    "game_theory": 0.75,
    "learner": 0.75,
    "investor_preference": 0.95,
    "verified_cache": 0.95,
    # 降级源 (Fallback)
    "eastmoney-news": 0.75,     # 东财新闻搜索 (T2)
    "eastmoney-global": 0.75,   # 东财7×24快讯 (T2)
    "eastmoney-report": 0.75,   # 东财研报 (T2)
    "akshare-screen": 0.70,     # AKShare 客户端选股降级 (T2)
}

# 数据源默认 T0-T3 分级
PROVIDER_SOURCE_TIER: dict[str, str] = {
    "cninfo": SOURCE_TIER_T0,
    "exchange": SOURCE_TIER_T0,
    "pboc": SOURCE_TIER_T0,
    "mootdx": SOURCE_TIER_T1,
    "guosen": SOURCE_TIER_T1,
    "tonghuashun": SOURCE_TIER_T1,
    "eastmoney": SOURCE_TIER_T1,
    "huatai": SOURCE_TIER_T1,
    "tencent": SOURCE_TIER_T2,
    "akshare": SOURCE_TIER_T2,
    "miaoxiang-data-executive": SOURCE_TIER_T2,
    "game_theory": SOURCE_TIER_T2,
    "learner": SOURCE_TIER_T2,
    "investor_preference": SOURCE_TIER_T1,
    "manual": SOURCE_TIER_T2,
    "llm_derived": SOURCE_TIER_T3,
    "verified_cache": SOURCE_TIER_T1,
    # 降级源
    "eastmoney-news": SOURCE_TIER_T2,
    "eastmoney-global": SOURCE_TIER_T2,
    "eastmoney-report": SOURCE_TIER_T2,
    "akshare-screen": SOURCE_TIER_T2,
}

# 统一缺口/未溯源标记
UNSOURCED_CITATION = SourceCitation(
    provider="unsourced",
    field="unknown",
    confidence=0.0,
    data_freshness=timedelta(seconds=0),
    source_tier=SOURCE_TIER_T3,
    nature=NATURE_SPECULATION,
)

# 数据类型新鲜度上限
FRESHNESS_LIMITS: dict[str, timedelta] = {
    "realtime_quote": timedelta(minutes=5),
    "daily_bar": timedelta(hours=1),
    "factor": timedelta(hours=1),
    "financials": timedelta(hours=24),
    "topic_policy": timedelta(hours=12),
    "analyst_report": timedelta(days=7),
    "announcement": timedelta(hours=24),
    "research_report": timedelta(days=7),
    "news_event": timedelta(hours=6),
    "executive_trade": timedelta(hours=4),
    "dividend": timedelta(hours=24),
    "stock_screening": timedelta(minutes=15),
    "fundamental": timedelta(hours=24),
    "executive": timedelta(hours=4),
    "industry_pe": timedelta(hours=24),
    "dividend_yield": timedelta(hours=24),
    "macro_indicator": timedelta(hours=4),
    "us_overnight": timedelta(hours=4),
}


def make_citation(
    provider: str,
    field: str,
    data_type: str = "daily_bar",
    url: str = "",
    is_cached: bool = False,
    source_tier: str | None = None,
    nature: str = NATURE_FACT,
    confidence: float | None = None,
) -> SourceCitation:
    """快捷创建 SourceCitation, 自动填充置信度、新鲜度和 T0-T3 分级。

    Args:
        provider: 数据源标识
        field: 数据字段名
        data_type: 数据类型 (realtime_quote/daily_bar/factor/financials/topic_policy/analyst_report/fundamental)
        url: 可选审计链接
        is_cached: 是否来自缓存
        source_tier: T0/T1/T2/T3，None 时按 provider 自动推断
        nature: 数据性质 (fact/interpretation/speculation/data_gap)
        confidence: 可选指定置信度；None 时按 provider 自动推断
    """
    tier = source_tier if source_tier is not None else PROVIDER_SOURCE_TIER.get(provider, SOURCE_TIER_T2)
    conf = confidence if confidence is not None else PROVIDER_CONFIDENCE.get(provider, 0.5)
    return SourceCitation(
        provider=provider,
        field=field,
        confidence=conf,
        data_freshness=FRESHNESS_LIMITS.get(data_type, timedelta(hours=1)),
        url_or_endpoint=url,
        is_cached=is_cached,
        source_tier=tier,
        nature=nature,
    )


def make_data_gap_citation(provider: str, field: str, reason: str = "") -> SourceCitation:
    """创建数据缺口标记 citation。"""
    return SourceCitation(
        provider=provider,
        field=field,
        confidence=0.0,
        data_freshness=timedelta(seconds=0),
        source_tier=SOURCE_TIER_T3,
        nature=NATURE_DATA_GAP,
        url_or_endpoint=reason,
    )
