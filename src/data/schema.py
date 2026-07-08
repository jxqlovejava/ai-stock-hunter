# -*- coding: utf-8 -*-
"""统一数据模型 — 所有数据源适配器输出此模块定义的结构。

设计原则:
  - 所有字段使用 Optional，缺失数据标注 None
  - source 字段追踪数据来源
  - cross_validated 和 dispute 字段支持双源交叉验证
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.data.source_citation import SourceCitation


# ---------------------------------------------------------------------------
# 时间分辨率
# ---------------------------------------------------------------------------


class Resolution(str, Enum):
    """K 线时间分辨率。

    参考 LEAN Resolution enum，适配 A 股实际数据源能力:
      - mootdx: 1min(8), 5min(0), daily(9), weekly(5), monthly(6)
      - 腾讯: 1min, 5min, 15min, 30min, 60min, daily, weekly, monthly
      - AKShare: 1min, 5min, 15min, 30min, 60min, daily, weekly, monthly
    """

    TICK = "tick"
    MIN_1 = "1min"
    MIN_5 = "5min"
    MIN_15 = "15min"
    MIN_30 = "30min"
    HOUR = "1hour"
    DAY = "daily"
    WEEK = "weekly"
    MONTH = "monthly"

    @property
    def total_minutes(self) -> int | None:
        """返回该分辨率对应的分钟数。tick 返回 None。"""
        _map = {
            Resolution.TICK: None,
            Resolution.MIN_1: 1,
            Resolution.MIN_5: 5,
            Resolution.MIN_15: 15,
            Resolution.MIN_30: 30,
            Resolution.HOUR: 60,
            Resolution.DAY: 240,
            Resolution.WEEK: 1200,
            Resolution.MONTH: 4800,
        }
        return _map[self]

    @property
    def is_intraday(self) -> bool:
        """是否为日内分辨率（分钟/小时/tick）。"""
        return self in (
            Resolution.TICK,
            Resolution.MIN_1,
            Resolution.MIN_5,
            Resolution.MIN_15,
            Resolution.MIN_30,
            Resolution.HOUR,
        )

    @property
    def pandas_freq(self) -> str | None:
        """pandas resample 对应的频率字符串。tick 返回 None。"""
        _map = {
            Resolution.TICK: None,
            Resolution.MIN_1: "1min",
            Resolution.MIN_5: "5min",
            Resolution.MIN_15: "15min",
            Resolution.MIN_30: "30min",
            Resolution.HOUR: "1h",
            Resolution.DAY: "1D",
            Resolution.WEEK: "1W",
            Resolution.MONTH: "1ME",
        }
        return _map[self]


# ---------------------------------------------------------------------------
# 行情数据
# ---------------------------------------------------------------------------

class Quote(BaseModel):
    """单只股票实时行情快照。"""

    symbol: str = Field(..., description="6 位股票代码")
    name: str = Field(..., description="股票名称")
    price: float = Field(..., description="最新价（元）")
    change_pct: float = Field(default=0.0, description="涨跌幅（%）")
    volume: int = Field(default=0, description="成交量（股）")
    turnover: float = Field(default=0.0, description="成交额（元）")
    high: Optional[float] = Field(default=None, description="最高价")
    low: Optional[float] = Field(default=None, description="最低价")
    open: Optional[float] = Field(default=None, description="开盘价")
    prev_close: Optional[float] = Field(default=None, description="前收盘价")
    limit_up: Optional[float] = Field(default=None, description="涨停价")
    limit_down: Optional[float] = Field(default=None, description="跌停价")
    # 估值字段 (Phase 5: 腾讯财经补全)
    pe_ttm: Optional[float] = Field(default=None, description="滚动市盈率")
    pe_static: Optional[float] = Field(default=None, description="静态市盈率")
    pb: Optional[float] = Field(default=None, description="市净率")
    market_cap: Optional[float] = Field(default=None, description="总市值（元）")
    dividend_yield: Optional[float] = Field(default=None, description="股息率 (%)")
    # 军规/准入门禁字段
    is_st: Optional[bool] = Field(default=None, description="是否为 ST/*ST")
    suspended: Optional[bool] = Field(default=None, description="是否停牌")
    listing_date: Optional[datetime] = Field(default=None, description="上市日期")
    # 数据溯源
    source: str = Field(..., description="数据来源: guosen / akshare")
    fetched_at: datetime = Field(default_factory=datetime.now)
    citation: Optional[SourceCitation] = Field(default=None, description="数据溯源引用")

    model_config = {"arbitrary_types_allowed": True}


class Bar(BaseModel):
    """单根 OHLCV K 线 — 时间序列的基本元素。

    与 Quote（实时快照，单时间点）不同，Bar 携带一个时间段内的
    开/高/低/收/量/额，是技术指标计算和回测的最小数据单元。

    参考 LEAN TradeBar / QuoteBar 模型。
    """

    symbol: str = Field(..., description="6 位股票代码")
    timestamp: datetime = Field(..., description="Bar 起始时间")
    resolution: Resolution = Field(..., description="时间分辨率")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: int = Field(default=0, description="成交量（股）")
    amount: float = Field(default=0.0, description="成交额（元）")
    source: str = Field(default="", description="数据来源")

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    @property
    def typical_price(self) -> float:
        """典型价格 (H+L+C)/3。"""
        return (self.high + self.low + self.close) / 3

    @property
    def weighted_close(self) -> float:
        """加权收盘价 (H+L+2*C)/4。"""
        return (self.high + self.low + 2 * self.close) / 4

    @property
    def is_rising(self) -> bool:
        """阳线。"""
        return self.close >= self.open

    @property
    def body_pct(self) -> float:
        """实体占比 (close-open)/open * 100。"""
        if self.open == 0:
            return 0.0
        return (self.close - self.open) / self.open * 100

    @property
    def upper_shadow_pct(self) -> float:
        """上影线占比。"""
        if self.open == 0:
            return 0.0
        body_high = max(self.open, self.close)
        return (self.high - body_high) / self.open * 100 if self.high > body_high else 0.0

    @property
    def lower_shadow_pct(self) -> float:
        """下影线占比。"""
        if self.open == 0:
            return 0.0
        body_low = min(self.open, self.close)
        return (body_low - self.low) / self.open * 100 if body_low > self.low else 0.0

    def to_dict(self) -> dict:
        """转为 dict，timestamp 格式化为 ISO 字符串。"""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "resolution": self.resolution.value,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "source": self.source,
        }


class TickData(BaseModel):
    """单笔分笔/tick 数据 — 最小粒度行情单元。

    A 股 tick 数据通常 3 秒一个快照（不是每笔成交），
    包含当时的价格、累计成交量和买卖方向。

    参考 LEAN Tick / TradeBar 输入源。
    """

    symbol: str = Field(..., description="6 位股票代码")
    timestamp: datetime = Field(..., description="Tick 时间戳")
    price: float = Field(..., description="成交价")
    volume: int = Field(default=0, description="本笔成交量（股）")
    cumulative_volume: int = Field(default=0, description="累计成交量（股）")
    amount: float = Field(default=0.0, description="本笔成交额（元）")
    cumulative_amount: float = Field(default=0.0, description="累计成交额（元）")
    direction: str = Field(default="NEUTRAL", description="买卖方向: BUY/SELL/NEUTRAL")
    source: str = Field(default="", description="数据来源")

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    @property
    def is_buy(self) -> bool:
        """主动性买盘。"""
        return self.direction == "BUY"

    @property
    def is_sell(self) -> bool:
        """主动性卖盘。"""
        return self.direction == "SELL"


# ---------------------------------------------------------------------------
# 财务数据
# ---------------------------------------------------------------------------

class Financials(BaseModel):
    """单期财务报表关键字段。"""

    symbol: str
    report_period: str = Field(..., description="报告期，如 '2025Q4'")
    revenue: Optional[float] = Field(default=None, description="营业收入（元）")
    net_profit: Optional[float] = Field(default=None, description="归母净利润（元）")
    total_assets: Optional[float] = Field(default=None, description="总资产（元）")
    total_liabilities: Optional[float] = Field(default=None, description="总负债（元）")
    operating_cash_flow: Optional[float] = Field(default=None, description="经营活动现金流（元）")
    roe: Optional[float] = Field(default=None, description="净资产收益率 (%)")
    eps: Optional[float] = Field(default=None, description="每股收益（元）")
    source: str = Field(..., description="数据来源")
    fetched_at: datetime = Field(default_factory=datetime.now)
    citation: Optional["SourceCitation"] = Field(default=None, description="数据溯源引用")


# ---------------------------------------------------------------------------
# 基本面指标（需交叉验证）
# ---------------------------------------------------------------------------

class FundamentalMetrics(BaseModel):
    """跨源聚合后的基本面指标。"""

    symbol: str
    name: str
    pe_ttm: Optional[float] = Field(default=None, description="市盈率 TTM")
    pb: Optional[float] = Field(default=None, description="市净率")
    roe: Optional[float] = Field(default=None, description="净资产收益率 (%)")
    debt_to_equity: Optional[float] = Field(default=None, description="资产负债率")
    market_cap: Optional[float] = Field(default=None, description="总市值（元）")
    sources: list[str] = Field(default_factory=list, description="数据来源列表")
    cross_validated: bool = Field(default=False, description="是否经过 ≥2 源交叉验证")
    dispute: bool = Field(default=False, description="多源差异 > 5%，数据可信度低")
    citations: list[SourceCitation] = Field(default_factory=list, description="各来源 citation")

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# 妙想 Skill 扩展 DTO (Phase: miaoxiang-integration)
# ---------------------------------------------------------------------------


class NewsItem(BaseModel):
    """mx-search 资讯搜索结果条目。"""

    title: str = Field(..., description="资讯标题")
    source: str = Field(default="", description="来源（如东方财富、证券时报）")
    date: str = Field(default="", description="发布日期")
    content: str = Field(default="", description="正文/摘要内容")
    secu_list: list[dict] = Field(default_factory=list, description="关联证券列表")
    url: str = Field(default="", description="原文链接")
    provider: str = Field(default="miaoxiang-search", description="数据提供方")


class RelatedParty(BaseModel):
    """mx-data 关联关系实体。"""

    entity_name: str = Field(..., description="关联方名称")
    relation_type: str = Field(default="", description="关系类型：股东/高管/子公司/关联交易")
    stake_pct: Optional[float] = Field(default=None, description="持股比例 (%)")
    position: str = Field(default="", description="职务")
    description: str = Field(default="", description="关系描述")
    provider: str = Field(default="miaoxiang-data", description="数据提供方")


class ScreeningResult(BaseModel):
    """mx-xuangu 选股筛选结果。"""

    symbol: str = Field(..., description="股票代码")
    name: str = Field(default="", description="股票简称")
    market: str = Field(default="", description="市场（SH/SZ）")
    price: Optional[float] = Field(default=None, description="最新价")
    change_pct: Optional[float] = Field(default=None, description="涨跌幅 (%)")
    pe_ttm: Optional[float] = Field(default=None, description="市盈率 TTM")
    pb: Optional[float] = Field(default=None, description="市净率")
    roe: Optional[float] = Field(default=None, description="净资产收益率 (%)")
    market_cap: Optional[float] = Field(default=None, description="总市值")
    extra_fields: dict = Field(default_factory=dict, description="来源返回的其他字段")
    provider: str = Field(default="miaoxiang-xuangu", description="数据提供方")


# ---------------------------------------------------------------------------
# 高管数据 (Phase: executive-data) — mx-data NL 查询
# ---------------------------------------------------------------------------


class ExecutiveTrade(BaseModel):
    """mx-data 高管增减持数据。"""

    executive_name: str = Field(..., description="高管姓名")
    position: str = Field(default="", description="职务")
    trade_type: str = Field(default="buy", description="buy/sell")
    trade_date: str = Field(default="", description="交易日期 YYYY-MM-DD")
    volume: Optional[int] = Field(default=None, description="变动股数")
    price: Optional[float] = Field(default=None, description="交易均价（元）")
    total_value: Optional[float] = Field(default=None, description="变动金额（元）")
    change_after_trade_pct: Optional[float] = Field(default=None, description="变动后持股比例 (%)")
    provider: str = Field(default="miaoxiang-data-executive", description="数据提供方")


class ExecutiveProfile(BaseModel):
    """mx-data 高管背景履历。"""

    name: str = Field(..., description="高管姓名")
    position: str = Field(default="", description="现任职务")
    age: Optional[int] = Field(default=None, description="年龄")
    education: str = Field(default="", description="学历")
    background: str = Field(default="", description="职业背景描述")
    tenure_start: str = Field(default="", description="任职起始日期")
    provider: str = Field(default="miaoxiang-data-executive", description="数据提供方")


class BoardChange(BaseModel):
    """mx-data 董监高变动。"""

    person_name: str = Field(..., description="变动人姓名")
    old_position: str = Field(default="", description="原职务")
    new_position: str = Field(default="", description="新职务")
    change_date: str = Field(default="", description="变动日期 YYYY-MM-DD")
    reason: str = Field(default="", description="变动原因：任期届满/辞职/换届/其他")
    provider: str = Field(default="miaoxiang-data-executive", description="数据提供方")


# ---------------------------------------------------------------------------
# Phase 4: Alpha Lens DTO 引用（统一入口）
# ---------------------------------------------------------------------------
# 核心 Alpha 类型从 src.alpha 模块导入，
# 此处提供便捷引用路径：from src.data.schema import AlphaProfile, AlphaSource, ...
from src.alpha.schema import (  # noqa: F401, E402
    AlphaDecayStatus,
    AlphaProfile,
    AlphaSource,
    ConsensusGap,
    NarrativeLifecycle,
    NarrativeStage,
    SourceTier,
)
