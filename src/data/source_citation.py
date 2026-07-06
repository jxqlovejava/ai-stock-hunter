# -*- coding: utf-8 -*-
"""统一数据溯源 — 所有分析输出必须携带 SourceCitation。

Phase 1: 护栏体系基础数据类型。
新增 Phase 1+: 数据级别（tier）与数据性质（nature）支持，用于数据质量加权。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


# 数据级别：一手 / 二手 / 三手
tier = str  # placeholder for type hints; actual constants below
TIER_PRIMARY = "primary"
TIER_SECONDARY = "secondary"
TIER_TERTIARY = "tertiary"

# 数据性质：事实 / 解释 / 推测
NATURE_FACT = "fact"
NATURE_INTERPRETATION = "interpretation"
NATURE_SPECULATION = "speculation"


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
    # Phase 1+: 数据级别与性质，用于质量加权
    tier: str = TIER_SECONDARY  # primary / secondary / tertiary
    nature: str = NATURE_FACT   # fact / interpretation / speculation

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
    def quality_score(self) -> float:
        """综合数据质量得分（0.0-1.0）。"""
        score = self.confidence
        if self.tier == TIER_PRIMARY:
            score = min(1.0, score * 1.10)
        elif self.tier == TIER_TERTIARY:
            score *= 0.85
        if self.nature == NATURE_INTERPRETATION:
            score *= 0.90
        elif self.nature == NATURE_SPECULATION:
            score *= 0.50
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
}

# 数据类型新鲜度上限
FRESHNESS_LIMITS: dict[str, timedelta] = {
    "realtime_quote": timedelta(minutes=5),
    "daily_bar": timedelta(hours=1),
    "factor": timedelta(hours=1),
    "financials": timedelta(hours=24),
    "topic_policy": timedelta(hours=12),
    "analyst_report": timedelta(days=7),
    "fundamental": timedelta(hours=24),
    "executive": timedelta(hours=4),
    "industry_pe": timedelta(hours=24),
    "dividend_yield": timedelta(hours=24),
    "macro_indicator": timedelta(hours=4),
}


def make_citation(
    provider: str,
    field: str,
    data_type: str = "daily_bar",
    url: str = "",
    is_cached: bool = False,
    tier: str = TIER_SECONDARY,
    nature: str = NATURE_FACT,
) -> SourceCitation:
    """快捷创建 SourceCitation, 自动填充置信度和新鲜度。

    Args:
        provider: 数据源标识
        field: 数据字段名
        data_type: 数据类型 (realtime_quote/daily_bar/factor/financials/topic_policy/analyst_report/fundamental)
        url: 可选审计链接
        is_cached: 是否来自缓存
        tier: 数据级别 (primary/secondary/tertiary)
        nature: 数据性质 (fact/interpretation/speculation)
    """
    return SourceCitation(
        provider=provider,
        field=field,
        confidence=PROVIDER_CONFIDENCE.get(provider, 0.5),
        data_freshness=FRESHNESS_LIMITS.get(data_type, timedelta(hours=1)),
        url_or_endpoint=url,
        is_cached=is_cached,
        tier=tier,
        nature=nature,
    )
