# -*- coding: utf-8 -*-
"""数据层 — 统一导出。"""

from .aggregator import DataAggregator
from .base import DataProvider
from .consolidators import (
    RenkoBar,
    RenkoConsolidator,
    RenkoDirection,
    TradeBarConsolidator,
    TimePeriodConsolidator,
    bars_to_dataframe,
    dataframe_to_bars,
)
from .cross_validator import validate_fundamentals, validate_price
from .feed import (
    DataFeed,
    FillForwardEnumerator,
    HistoricalDataFeed,
    Subscription,
    SubscriptionConfig,
    SubscriptionManager,
)
from .schema import (
    Bar,
    Financials,
    FundamentalMetrics,
    NewsItem,
    Quote,
    RelatedParty,
    Resolution,
    ScreeningResult,
    TickData,
)

__all__ = [
    # 数据源
    "DataProvider",
    "DataAggregator",
    # 行情模型
    "Quote",
    "Bar",
    "TickData",
    "Resolution",
    # 聚合器
    "TradeBarConsolidator",
    "TimePeriodConsolidator",
    "RenkoConsolidator",
    "RenkoBar",
    "RenkoDirection",
    "bars_to_dataframe",
    "dataframe_to_bars",
    # 数据馈送
    "DataFeed",
    "HistoricalDataFeed",
    "Subscription",
    "SubscriptionConfig",
    "SubscriptionManager",
    "FillForwardEnumerator",
    # 财务模型
    "Financials",
    "FundamentalMetrics",
    # 资讯 & 关联
    "NewsItem",
    "RelatedParty",
    "ScreeningResult",
    # 校验
    "validate_price",
    "validate_fundamentals",
]
