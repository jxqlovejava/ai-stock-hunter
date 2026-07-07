# -*- coding: utf-8 -*-
"""均线支撑距离 — 价格到最近均线支撑的距离。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, ts_mean

__alpha_meta__ = {
    "id": "ma_support",
    "nickname": "MA Support",
    "category": "technical",
    "description": "价格到最近均线(MA5/10/20/60)支撑位的距离 — 靠近支撑得分高(低吸机会)",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ma5 = ts_mean(close, 5)
    ma10 = ts_mean(close, 10)
    ma20 = ts_mean(close, 20)
    ma60 = ts_mean(close, 60)

    # 价格在均线上方时，均线是支撑。找最近的上方均线。
    # 距离 = (price - nearest_support_ma) / price，越小越好
    supports = []
    for ma in [ma5, ma10, ma20, ma60]:
        supports.append((close - ma) / (close + 1e-12))

    # 取最小的正乖离（最近的支撑），负乖离=跌破
    stacked = np.stack([s.fillna(0).values for s in supports], axis=-1)
    min_positive = np.where(
        stacked > 0,
        stacked,
        np.inf,
    ).min(axis=-1)

    result = pd.DataFrame(min_positive, index=close.index, columns=close.columns)

    # 距离越近（小正数）得分越高，跌破（inf→0）得分低
    score = 100.0 * np.exp(-result * 15.0)
    return score.fillna(0).clip(lower=0)
