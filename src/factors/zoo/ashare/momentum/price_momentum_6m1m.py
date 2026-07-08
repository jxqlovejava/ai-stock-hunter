# -*- coding: utf-8 -*-
"""6-1 月价格动量因子。

MOM_{6-1} = (P_{t-1} - P_{t-6}) / P_{t-6}

A 股适配: 6 个月动量在 A 股表现弱于 3 个月，但强于 12 个月。
与 3-1 月因子组合使用时需注意共线性。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__alpha_meta__ = {
    "id": "price_momentum_6m1m",
    "nickname": "6-1月动量",
    "category": "momentum",
    "description": "6 个月动量跳过最近 1 个月，(P_{t-1} - P_{t-6}) / P_{t-6}",
    "columns_required": ["close"],
    "frequency": "daily",
    "min_warmup_bars": 126,
    "provider_confidence": 0.80,
    "tags": ["momentum", "price", "medium_term"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    results: dict[str, float] = {}

    for symbol, df in panel.items():
        if df.empty or "close" not in df.columns:
            results[symbol] = np.nan
            continue

        close = df["close"].astype(float)

        if len(close) < 126:
            results[symbol] = np.nan
            continue

        p_t_minus_1m = close.iloc[-21] if len(close) >= 21 else close.iloc[-1]
        p_t_minus_6m = close.iloc[-126]

        if p_t_minus_6m > 0:
            momentum = (p_t_minus_1m - p_t_minus_6m) / p_t_minus_6m
        else:
            momentum = np.nan

        results[symbol] = momentum

    return pd.DataFrame(
        {"price_momentum_6m1m": results.values()},
        index=results.keys(),
    )
