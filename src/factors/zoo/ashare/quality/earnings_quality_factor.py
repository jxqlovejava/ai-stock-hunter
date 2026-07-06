# -*- coding: utf-8 -*-
"""盈利质量因子：经营现金流 / 净利润。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank, safe_div

__alpha_meta__ = {
    "id": "earnings_quality_factor",
    "nickname": "Cash Earnings Ratio",
    "category": "quality",
    "description": "经营现金流覆盖净利润程度越高得分越高",
    "columns_required": ["operating_cashflow", "net_profit"],
    "frequency": ["quarterly", "daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    np_clipped = panel["net_profit"].clip(lower=1.0)
    ratio = safe_div(panel["operating_cashflow"], np_clipped)
    ratio = ratio.clip(lower=0, upper=5)
    return rank(ratio) * 100.0
