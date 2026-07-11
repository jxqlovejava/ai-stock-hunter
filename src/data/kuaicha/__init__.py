# -*- coding: utf-8 -*-
"""快查 (Kuaicha) 企业数据引擎集成。

iwencai (21 tools): A股选股/技术分析/财务/龙虎榜/北向/机构调研/宏观等
listed (9 tools): 三表/十大股东/董监高/审计意见等

Usage:
    from src.data.kuaicha import KuaichaClient
    client = KuaichaClient()
    result = client.iwencai_query("astock_finance", "同花顺 最新季度 ROE 净利润 毛利率")
    holders = client.listed_query("get_stock_ten_hold", orgid="T000025753")
"""

from .client import KuaichaClient
from .schemas import (
    IWencaiResult,
    ListedResult,
)

__all__ = ["KuaichaClient", "IWencaiResult", "ListedResult"]
