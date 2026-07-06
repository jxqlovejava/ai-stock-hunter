# -*- coding: utf-8 -*-
"""营收增速成长因子。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "revenue_growth_factor",
    "nickname": "Revenue Growth",
    "category": "growth",
    "description": "营收同比增速越高得分越高",
    "columns_required": ["revenue_growth"],
    "frequency": ["quarterly", "daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    growth = panel["revenue_growth"]
    return rank(growth) * 100.0
