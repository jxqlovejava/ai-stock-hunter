# -*- coding: utf-8 -*-
"""DMI 方向指标 — 趋势方向与力度。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "dmi_direction",
    "nickname": "DMI Direction",
    "category": "technical",
    "description": "+DI 减 -DI 乘以 ADX缩放 — 正值且 ADX>25=多头趋势确立，高分",
    "columns_required": ["high", "low", "close"],
    "frequency": ["daily"],
    "min_warmup_bars": 30,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    high, low, close = panel["high"], panel["low"], panel["close"]
    n = 14

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.DataFrame(
        np.maximum(np.maximum(tr1.values, tr2.values), tr3.values),
        index=tr1.index,
        columns=tr1.columns,
    )

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = pd.DataFrame(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0),
        index=high.index, columns=high.columns,
    )
    minus_dm = pd.DataFrame(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0),
        index=low.index, columns=low.columns,
    )

    atr = tr.rolling(n, min_periods=n).mean()
    plus_di = 100.0 * plus_dm.rolling(n, min_periods=n).mean() / (atr + 1e-12)
    minus_di = 100.0 * minus_dm.rolling(n, min_periods=n).mean() / (atr + 1e-12)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
    adx = dx.rolling(n, min_periods=n).mean()

    direction = plus_di - minus_di
    adx_scaled = adx / 100.0
    score = direction * adx_scaled
    return rank(score) * 100.0
