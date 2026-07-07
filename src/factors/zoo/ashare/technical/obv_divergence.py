# -*- coding: utf-8 -*-
"""OBV 背离 — 量价趋势一致性检测。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "obv_divergence",
    "nickname": "OBV Divergence",
    "category": "technical",
    "description": "OBV与价格20日滚动相关性 — 正相关=量价配合(高分)，负相关=背离预警(低分)",
    "columns_required": ["close", "volume"],
    "frequency": ["daily"],
    "min_warmup_bars": 22,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close, volume = panel["close"], panel["volume"]
    direction = np.sign(close.diff(1))
    obv = (direction * volume).cumsum()
    obv_chg = obv.diff(20)
    price_chg = close.diff(20)
    corr = obv_chg.rolling(20, min_periods=10).corr(price_chg)
    return rank(corr.fillna(0)) * 100.0
