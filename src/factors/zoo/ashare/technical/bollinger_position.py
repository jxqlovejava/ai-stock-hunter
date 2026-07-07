# -*- coding: utf-8 -*-
"""布林带位置 — 价格在布林带中的相对位置。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import ts_mean, ts_std

__alpha_meta__ = {
    "id": "bollinger_position",
    "nickname": "Bollinger Position",
    "category": "technical",
    "description": "价格在布林带(20,2)中的位置 — 中轨=最优，下轨附近=超卖反弹，上轨=超买",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ma = ts_mean(close, 20)
    std = ts_std(close, 20)
    bb_upper = ma + 2.0 * std
    bb_lower = ma - 2.0 * std
    position = (close - bb_lower) / (bb_upper - bb_lower + 1e-12)  # 0-1

    # 中轨(0.5)附近最优，两端递减
    score = 100.0 * (1.0 - 2.0 * np.abs(position - 0.5))
    return score.clip(lower=0)
