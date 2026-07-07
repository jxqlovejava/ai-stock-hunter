# -*- coding: utf-8 -*-
"""MA 乖离率 — 价格偏离 20 日均线的程度。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import safe_div, ts_mean

__alpha_meta__ = {
    "id": "ma_bias",
    "nickname": "MA Bias",
    "category": "technical",
    "description": "价格相对20日均线乖离率 — 正乖离大=超买，负乖离大=超卖，-3%~+3% 中性最优",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ma20 = ts_mean(close, 20)
    bias = safe_div(close - ma20, ma20)
    score = 100.0 * (1.0 - np.abs(np.clip(bias, -0.15, 0.15)) / 0.15)
    return score.clip(lower=0)
