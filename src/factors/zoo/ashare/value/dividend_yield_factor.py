# -*- coding: utf-8 -*-
"""高股息率价值因子。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "dividend_yield_factor",
    "nickname": "High Dividend Yield",
    "category": "value",
    "description": "高股息率股票得分高",
    "columns_required": ["dividend_yield"],
    "frequency": ["daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    dy = panel["dividend_yield"]
    dy_positive = dy.where(dy > 0)
    return rank(dy_positive) * 100.0
