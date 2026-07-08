# -*- coding: utf-8 -*-
"""12-1 月价格动量因子 — 经典 Carhart (1997) 动量因子。

MOM_{12-1} = (P_{t-1} - P_{t-12}) / P_{t-12}
跳过最近一个月以消除短期反转效应。

A 股适配: 长周期动量在 A 股弱于美股，但仍有 IC>0.01 的正信号。
适合与其他因子组合使用，不宜作为单一选股因子。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__alpha_meta__ = {
    "id": "price_momentum_12m1m",
    "nickname": "12-1月动量",
    "category": "momentum",
    "description": "12 个月动量跳过最近 1 个月，(P_{t-1} - P_{t-12}) / P_{t-12}",
    "columns_required": ["close"],
    "frequency": "daily",
    "min_warmup_bars": 252,
    "provider_confidence": 0.85,
    "tags": ["momentum", "carhart", "price", "long_term"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """计算 12-1 月动量因子。

    Args:
        panel: {symbol: DataFrame}, DataFrame 须包含 "close" 列

    Returns:
        DataFrame，index=symbols, columns=["price_momentum_12m1m"]
    """
    results: dict[str, float] = {}

    for symbol, df in panel.items():
        if df.empty or "close" not in df.columns:
            results[symbol] = np.nan
            continue

        close = df["close"].astype(float)

        # 需要至少 252 个交易日 (~12 个月)
        if len(close) < 252:
            results[symbol] = np.nan
            continue

        # P_{t-21} ~ 1 个月前 (约 21 个交易日)
        p_t_minus_1m = close.iloc[-21] if len(close) >= 21 else close.iloc[-1]
        # P_{t-252} ~ 12 个月前
        p_t_minus_12m = close.iloc[-252]

        if p_t_minus_12m > 0:
            momentum = (p_t_minus_1m - p_t_minus_12m) / p_t_minus_12m
        else:
            momentum = np.nan

        results[symbol] = momentum

    return pd.DataFrame(
        {"price_momentum_12m1m": results.values()},
        index=results.keys(),
    )
