# -*- coding: utf-8 -*-
"""数据层 — 统一导出。"""

from .aggregator import DataAggregator
from .base import DataProvider
from .cross_validator import validate_fundamentals, validate_price
from .schema import (
    Financials,
    FundamentalMetrics,
    NewsItem,
    Quote,
    RelatedParty,
    ScreeningResult,
)

__all__ = [
    "DataProvider",
    "DataAggregator",
    "Quote",
    "Financials",
    "FundamentalMetrics",
    "NewsItem",
    "RelatedParty",
    "ScreeningResult",
    "validate_price",
    "validate_fundamentals",
]
