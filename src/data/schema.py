# -*- coding: utf-8 -*-
"""统一数据模型 — 所有数据源适配器输出此模块定义的结构。

设计原则:
  - 所有字段使用 Optional，缺失数据标注 None
  - source 字段追踪数据来源
  - cross_validated 和 dispute 字段支持双源交叉验证
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


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
    source: str = Field(..., description="数据来源: guosen / akshare")
    fetched_at: datetime = Field(default_factory=datetime.now)


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
    source: str = Field(..., description="数据来源")
    fetched_at: datetime = Field(default_factory=datetime.now)


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
