# -*- coding: utf-8 -*-
"""已实现波动率因子 — 低波动异象（低波动股票长期跑赢）。"""

from __future__ import annotations

import pandas as pd
import numpy as np

from src.factors.base import rank

__alpha_meta__ = {
    "id": "realized_vol",
    "nickname": "Realized Vol",
    "category": "volatility",
    "description": "20日已实现波动率越低→得分越高（低波动异象）",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ret = close.pct_change()
    realized = ret.rolling(window=20, min_periods=5).std() * np.sqrt(252)
    # 低波动 = 高分
    return (1.0 - rank(realized)) * 100.0
