# -*- coding: utf-8 -*-
"""低 PS 价值因子。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "ps_factor",
    "nickname": "Low PS",
    "category": "value",
    "description": "低市销率股票得分高",
    "columns_required": ["ps"],
    "frequency": ["daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ps = panel["ps"]
    ps_positive = ps.where(ps > 0)
    return (1.0 - rank(ps_positive)) * 100.0
