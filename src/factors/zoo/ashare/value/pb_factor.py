# -*- coding: utf-8 -*-
"""低 PB 价值因子。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "pb_factor",
    "nickname": "Low PB",
    "category": "value",
    "description": "低市净率股票得分高",
    "columns_required": ["pb"],
    "frequency": ["daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pb = panel["pb"]
    # 过滤非正 PB
    pb_positive = pb.where(pb > 0)
    # 低 PB → 高分：invert rank
    return (1.0 - rank(pb_positive)) * 100.0
