# -*- coding: utf-8 -*-
"""下行波动率因子 — 低下行波动=高分（防御属性）。"""

from __future__ import annotations

import pandas as pd
import numpy as np

from src.factors.base import rank

__alpha_meta__ = {
    "id": "downside_vol",
    "nickname": "Downside Vol",
    "category": "volatility",
    "description": "下行波动率越低→防御性越强→得分越高",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ret = close.pct_change()
    # 下行收益（仅负收益）
    downside = ret.where(ret < 0, 0.0)
    # 20 日下行波动率
    down_vol = downside.rolling(window=20, min_periods=5).std()
    # 低波动 = 高分（反向排名）
    return (1.0 - rank(down_vol)) * 100.0
