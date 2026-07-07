# -*- coding: utf-8 -*-
"""均线排列评分 — MA5/10/20/60 多头/空头排列程度。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, ts_mean

__alpha_meta__ = {
    "id": "ma_alignment",
    "nickname": "MA Alignment",
    "category": "technical",
    "description": "MA5/10/20/60多头排列程度 — 完全多头(MA5>MA10>MA20>MA60)得分最高",
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

    # 统计多头排列的对数 (共6对相邻比较)
    score = (
        (ma5 > ma10).astype(float)
        + (ma10 > ma20).astype(float)
        + (ma20 > ma60).astype(float)
        + (ma5 > ma20).astype(float)
        + (ma5 > ma60).astype(float)
        + (ma10 > ma60).astype(float)
    ) / 6.0 * 100.0

    # 加入排序强度（rank）平滑
    return rank(score) * 100.0
