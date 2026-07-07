# -*- coding: utf-8 -*-
"""MACD 柱状图 — 趋势强度与方向。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank, safe_div

__alpha_meta__ = {
    "id": "macd_histogram",
    "nickname": "MACD Histogram",
    "category": "technical",
    "description": "MACD柱状图(DIF-DEA)*2 — 正值扩大=强势上涨，负值收窄=筑底，零轴上方得分高",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 35,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ema12 = close.ewm(span=12, min_periods=12).mean()
    ema26 = close.ewm(span=26, min_periods=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, min_periods=9).mean()
    histogram = (dif - dea) * 2.0
    normalized = safe_div(histogram, close)
    return rank(normalized) * 100.0
