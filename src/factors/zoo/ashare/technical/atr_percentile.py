# -*- coding: utf-8 -*-
"""ATR 百分位 — 波动率位置判断。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import ts_max, ts_mean, ts_min

__alpha_meta__ = {
    "id": "atr_percentile",
    "nickname": "ATR Percentile",
    "category": "technical",
    "description": "14日ATR在60日历史中的百分位 — 低波动(<30%)得分高(稳定)，高波动(>80%)预警",
    "columns_required": ["high", "low", "close"],
    "frequency": ["daily"],
    "min_warmup_bars": 75,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    high, low, close = panel["high"], panel["low"], panel["close"]

    # True Range: max of 3 components, computed per-column to preserve DataFrame shape
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = pd.DataFrame(
        np.maximum(np.maximum(tr1.values, tr2.values), tr3.values),
        index=tr1.index,
        columns=tr1.columns,
    )

    atr14 = tr.rolling(14, min_periods=14).mean()
    atr_high60 = ts_max(atr14, 60)
    atr_low60 = ts_min(atr14, 60)

    percentile = (atr14 - atr_low60) / (atr_high60 - atr_low60 + 1e-12)

    # 低波动 = 高分（筹码稳定），高波动 > 80% = 低分（不确定性强）
    score = 100.0 * (1.0 - np.clip(percentile, 0, 1))
    return pd.DataFrame(score, index=atr14.index, columns=atr14.columns).clip(lower=0)
