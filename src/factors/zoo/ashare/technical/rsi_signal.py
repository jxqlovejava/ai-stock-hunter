# -*- coding: utf-8 -*-
"""RSI 信号 — 超买超卖判断。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import safe_div

__alpha_meta__ = {
    "id": "rsi_signal",
    "nickname": "RSI Signal",
    "category": "technical",
    "description": "14日RSI — 40-55中性区得分最高，<30超卖(反转机会)，>70超买(风险)",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 15,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    delta_close = close.diff(1)
    gain = delta_close.clip(lower=0)
    loss = (-delta_close).clip(lower=0)
    avg_gain = gain.ewm(com=13, min_periods=14).mean()
    avg_loss = loss.ewm(com=13, min_periods=14).mean()
    rs = safe_div(avg_gain, avg_loss)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    score = 100.0 * (1.0 - np.abs(rsi - 45.0) / 55.0)
    return score.clip(lower=0)
