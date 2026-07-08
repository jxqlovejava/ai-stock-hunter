# -*- coding: utf-8 -*-
"""成交量异动因子 — 放量上涨=强势信号，放量下跌=弱势信号。"""

from __future__ import annotations

import pandas as pd
import numpy as np

from src.factors.base import rank

__alpha_meta__ = {
    "id": "volume_surge_signal",
    "nickname": "Volume Surge Signal",
    "category": "flow",
    "description": "放量上涨→强势→高分；放量下跌→弱势→低分",
    "columns_required": ["close", "volume"],
    "frequency": ["daily"],
    "min_warmup_bars": 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    vol = panel["volume"]
    ret = close.pct_change()
    avg_vol = vol.rolling(window=20, min_periods=5).mean()
    vol_ratio = vol / (avg_vol + 1e-9)
    # 放量信号 = 收益率 × 量比（量价配合）
    signal = ret * np.log(vol_ratio.clip(0.1, 10))
    # 5 日平滑
    return rank(signal.rolling(window=5, min_periods=1).mean()) * 100.0
