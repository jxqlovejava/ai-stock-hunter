# -*- coding: utf-8 -*-
"""Kuaicha 数据模型 — iwencai/listed 响应 DTOs。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# iwencai — 自然语言查询响应
# ---------------------------------------------------------------------------


class IWencaiResult(BaseModel):
    """iwencai 工具返回的数据封装。

    iwencai 工具统一返回 JSON，但各工具返回结构不同（选股/技术/
    财务/龙虎榜/北向/机构/宏观/行业等），用 raw_data 承载原始响应。
    """

    tool_name: str = Field(..., description="调用的 iwencai 工具名，如 astock_finance")
    query: str = Field(..., description="查询的自然语言文本")
    raw_data: list[dict[str, Any]] = Field(
        default_factory=list, description="原始返回数据"
    )
    total_count: int = Field(default=0, description="返回条数")
    fetched_at: datetime = Field(
        default_factory=datetime.now, description="获取时间"
    )
    provider: str = Field(default="kuaicha-iwencai", description="数据来源")


# ---------------------------------------------------------------------------
# listed — 结构化查询响应
# ---------------------------------------------------------------------------


class ListedResult(BaseModel):
    """listed 工具返回的数据封装。

    覆盖: 三表/十大股东/十大流通股东/董监高/审计意见。
    """

    tool_name: str = Field(
        ..., description="调用的 listed 工具名，如 get_income_statement"
    )
    params: dict[str, object] = Field(
        default_factory=dict, description="调用参数"
    )
    raw_data: list[dict[str, Any]] = Field(
        default_factory=list, description="原始返回数据"
    )
    total_count: int = Field(default=0, description="返回条数")
    fetched_at: datetime = Field(
        default_factory=datetime.now, description="获取时间"
    )
    provider: str = Field(default="kuaicha-listed", description="数据来源")


# ---------------------------------------------------------------------------
# 财务三表 — normalized DTOs
# ---------------------------------------------------------------------------


class KuaichaIncomeStatement(BaseModel):
    """利润表标准化字段。"""

    report_period: str = Field(default="", description="报告期")
    report_type: str = Field(default="", description="财报类型: HB-合并/MGS-母公司")
    revenue: Optional[float] = Field(default=None, description="营业总收入(元)")
    operating_cost: Optional[float] = Field(default=None, description="营业总成本(元)")
    operating_profit: Optional[float] = Field(default=None, description="营业利润(元)")
    net_profit: Optional[float] = Field(default=None, description="净利润(元)")
    net_profit_parent: Optional[float] = Field(
        default=None, description="归属母公司净利润(元)"
    )
    eps_basic: Optional[float] = Field(default=None, description="基本每股收益(元)")
    is_audited: bool = Field(default=False, description="是否已审计")


class KuaichaBalanceSheet(BaseModel):
    """资产负债表标准化字段。"""

    report_period: str = Field(default="", description="报告期")
    report_type: str = Field(default="", description="财报类型")
    total_assets: Optional[float] = Field(default=None, description="资产总计(元)")
    total_liabilities: Optional[float] = Field(default=None, description="负债合计(元)")
    equity_parent: Optional[float] = Field(
        default=None, description="归属母公司所有者权益(元)"
    )
    goodwill: Optional[float] = Field(default=None, description="商誉(元)")
    current_assets: Optional[float] = Field(default=None, description="流动资产(元)")
    current_liabilities: Optional[float] = Field(
        default=None, description="流动负债(元)"
    )
    is_audited: bool = Field(default=False, description="是否已审计")


class KuaichaCashFlow(BaseModel):
    """现金流量表标准化字段。"""

    report_period: str = Field(default="", description="报告期")
    report_type: str = Field(default="", description="财报类型")
    operating_cf: Optional[float] = Field(
        default=None, description="经营活动现金流量净额(元)"
    )
    investing_cf: Optional[float] = Field(
        default=None, description="投资活动现金流量净额(元)"
    )
    financing_cf: Optional[float] = Field(
        default=None, description="筹资活动现金流量净额(元)"
    )
    is_audited: bool = Field(default=False, description="是否已审计")
