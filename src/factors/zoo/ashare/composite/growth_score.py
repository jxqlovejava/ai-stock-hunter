# -*- coding: utf-8 -*-
"""综合成长得分：营收增速 (50%) + 净利润增速 (50%)。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "growth_score",
    "nickname": "Composite Growth",
    "category": "composite",
    "description": "综合成长得分",
    "columns_required": ["revenue_growth", "earnings_growth"],
    "frequency": ["quarterly", "daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rev_score = rank(panel["revenue_growth"]) * 100.0
    earn_score = rank(panel["earnings_growth"]) * 100.0
    return rev_score * 0.50 + earn_score * 0.50
