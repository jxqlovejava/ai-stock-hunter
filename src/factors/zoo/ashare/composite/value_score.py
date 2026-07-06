# -*- coding: utf-8 -*-
"""综合价值得分：PB (40%) + PS (30%) + 股息率 (30%)。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank, safe_div

__alpha_meta__ = {
    "id": "value_score",
    "nickname": "Composite Value",
    "category": "composite",
    "description": "综合价值得分",
    "columns_required": ["pb", "ps", "dividend_yield"],
    "frequency": ["daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pb = panel["pb"].where(panel["pb"] > 0)
    ps = panel["ps"].where(panel["ps"] > 0)
    dy = panel["dividend_yield"].where(panel["dividend_yield"] > 0)

    pb_score = (1.0 - rank(pb)) * 100.0
    ps_score = (1.0 - rank(ps)) * 100.0
    dy_score = rank(dy) * 100.0

    return pb_score * 0.40 + ps_score * 0.30 + dy_score * 0.30
