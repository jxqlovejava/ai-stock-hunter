# -*- coding: utf-8 -*-
"""成交量比率 — 相对放量/缩量程度。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import safe_div, ts_mean

__alpha_meta__ = {
    "id": "volume_ratio",
    "nickname": "Volume Ratio",
    "category": "technical",
    "description": "当日成交量/20日均量 — 1.5倍最优(温和放量)，<0.5缩量或>5倍异常放量得分低",
    "columns_required": ["volume"],
    "frequency": ["daily"],
    "min_warmup_bars": 21,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    volume = panel["volume"]
    ma_vol = ts_mean(volume, 20)
    ratio = safe_div(volume, ma_vol)
    deviation = np.abs(ratio - 1.5) / 1.5
    score = 100.0 * np.exp(-deviation * 2.0)
    return score.clip(lower=0)
