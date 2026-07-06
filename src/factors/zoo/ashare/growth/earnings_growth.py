# -*- coding: utf-8 -*-
"""净利润增速成长因子。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "earnings_growth_factor",
    "nickname": "Earnings Growth",
    "category": "growth",
    "description": "净利润同比增速越高得分越高",
    "columns_required": ["earnings_growth"],
    "frequency": ["quarterly", "daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    growth = panel["earnings_growth"]
    return rank(growth) * 100.0
