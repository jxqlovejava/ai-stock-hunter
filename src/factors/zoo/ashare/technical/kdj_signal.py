# -*- coding: utf-8 -*-
"""KDJ 信号 — 随机指标综合评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import safe_div, ts_max, ts_min

__alpha_meta__ = {
    "id": "kdj_signal",
    "nickname": "KDJ Signal",
    "category": "technical",
    "description": "KDJ指标 — K值低位(20-50)+J值非超买区得分高，预示金叉反弹",
    "columns_required": ["high", "low", "close"],
    "frequency": ["daily"],
    "min_warmup_bars": 15,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    high, low, close = panel["high"], panel["low"], panel["close"]
    n = 9
    lowest = ts_min(low, n)
    highest = ts_max(high, n)
    rsv = 100.0 * safe_div(close - lowest, highest - lowest)

    k = rsv.copy()
    d = rsv.copy()
    for i in range(1, len(rsv)):
        k.iloc[i] = 2.0 / 3.0 * k.iloc[i - 1] + 1.0 / 3.0 * rsv.iloc[i]
        d.iloc[i] = 2.0 / 3.0 * d.iloc[i - 1] + 1.0 / 3.0 * k.iloc[i]
    j = 3.0 * k - 2.0 * d

    k_score = 100.0 * (1.0 - np.abs(k - 35.0) / 65.0)
    j_penalty = pd.DataFrame(
        np.where(j > 100, (j - 100) * 0.5, 0),
        index=j.index, columns=j.columns,
    )
    j_bonus = pd.DataFrame(
        np.where(j < 0, np.abs(j) * 0.3, 0),
        index=j.index, columns=j.columns,
    )
    score = (k_score - j_penalty + j_bonus).clip(0, 100)
    return score
