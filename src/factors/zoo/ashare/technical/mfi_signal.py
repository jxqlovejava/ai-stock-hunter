# -*- coding: utf-8 -*-
"""MFI 资金流向指标 — 量价结合的 RSI。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import safe_div

__alpha_meta__ = {
    "id": "mfi_signal",
    "nickname": "MFI Signal",
    "category": "technical",
    "description": "14日资金流向指标 — 50中性最优，<20超卖(资金流出枯竭)，>80超买(资金过热)",
    "columns_required": ["high", "low", "close", "volume"],
    "frequency": ["daily"],
    "min_warmup_bars": 15,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    high, low, close, volume = panel["high"], panel["low"], panel["close"], panel["volume"]
    typical = (high + low + close) / 3.0
    money_flow = typical * volume

    tp_diff = typical.diff(1)
    positive_flow = pd.DataFrame(
        np.where(tp_diff > 0, money_flow, 0),
        index=money_flow.index, columns=money_flow.columns,
    )
    negative_flow = pd.DataFrame(
        np.where(tp_diff < 0, money_flow, 0),
        index=money_flow.index, columns=money_flow.columns,
    )

    n = 14
    pos_sum = positive_flow.rolling(n, min_periods=n).sum()
    neg_sum = negative_flow.rolling(n, min_periods=n).sum()
    money_ratio = safe_div(pos_sum, neg_sum)
    mfi = 100.0 - (100.0 / (1.0 + money_ratio))

    score = 100.0 * (1.0 - np.abs(mfi - 50.0) / 50.0)
    return score.clip(lower=0)
