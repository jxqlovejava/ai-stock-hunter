# -*- coding: utf-8 -*-
"""3-1 月价格动量因子 — A 股特有强动量区间。

MOM_{3-1} = (P_{t-1} - P_{t-3}) / P_{t-3}

A 股特征: 1-3 个月是 A 股动量效应最强的区间。
散户追涨行为驱动短期正反馈，3-1 月动量因子 IC 通常 > 0.03。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__alpha_meta__ = {
    "id": "price_momentum_3m1m",
    "nickname": "3-1月动量",
    "category": "momentum",
    "description": "3 个月动量跳过最近 1 个月，(P_{t-1} - P_{t-3}) / P_{t-3}。A 股最强动量区间",
    "columns_required": ["close"],
    "frequency": "daily",
    "min_warmup_bars": 63,
    "provider_confidence": 0.90,
    "tags": ["momentum", "price", "short_term", "a_share_specific"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    results: dict[str, float] = {}

    for symbol, df in panel.items():
        if df.empty or "close" not in df.columns:
            results[symbol] = np.nan
            continue

        close = df["close"].astype(float)

        if len(close) < 63:
            results[symbol] = np.nan
            continue

        p_t_minus_1m = close.iloc[-21] if len(close) >= 21 else close.iloc[-1]
        p_t_minus_3m = close.iloc[-63]

        if p_t_minus_3m > 0:
            momentum = (p_t_minus_1m - p_t_minus_3m) / p_t_minus_3m
        else:
            momentum = np.nan

        results[symbol] = momentum

    return pd.DataFrame(
        {"price_momentum_3m1m": results.values()},
        index=results.keys(),
    )
