# -*- coding: utf-8 -*-
"""威廉指标 — 超买超卖极值反转信号。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import ts_max, ts_min

__alpha_meta__ = {
    "id": "williams_r",
    "nickname": "Williams %R",
    "category": "technical",
    "description": "14日威廉指标(-100~0) — -50中性最优，<-80超卖(反弹)，>-20超买(回调)",
    "columns_required": ["high", "low", "close"],
    "frequency": ["daily"],
    "min_warmup_bars": 15,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    high, low, close = panel["high"], panel["low"], panel["close"]
    n = 14
    highest = ts_max(high, n)
    lowest = ts_min(low, n)
    wr = -100.0 * (highest - close) / (highest - lowest + 1e-12)
    score = 100.0 * (1.0 - np.abs(wr + 50.0) / 50.0)
    return score.clip(lower=0)
