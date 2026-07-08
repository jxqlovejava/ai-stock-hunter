# -*- coding: utf-8 -*-
"""Finance 数据元工具 — NL 驱动财务查询系统。

基于 Dexter 模式: 自然语言 → parse → 子工具执行 → 格式化输出。

使用示例:
    from src.finance.meta_tool import MetaTool

    mt = MetaTool()
    mt.execute("营收 600519 3")          # 茅台最近 3 年营收
    mt.execute("对比 600519 vs 000858 营收")  # 茅台 vs 五粮液
    mt.execute("关键比率 600519")         # 关键财务比率
    mt.execute("K线 600519 日")          # 日 K 线
    mt.execute("新闻 600519 5")          # 最近 5 条新闻
"""

from __future__ import annotations

from .meta_tool import MetaTool
from . import formatters, sub_tools

__all__ = [
    "MetaTool",
    "formatters",
    "sub_tools",
]
