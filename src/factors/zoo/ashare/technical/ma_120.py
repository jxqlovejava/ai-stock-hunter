# -*- coding: utf-8 -*-
"""MA120 中长期方向 — 价格相对 MA120 位置 + MA120 斜率。

供 P1-2 均线定方向：MA120 是半年线的近似，用于判断中长期趋势方向。
得分高 = 价格站上 MA120 且 MA120 上行（中长期多头）；得分低 = 空头。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import ts_mean

__alpha_meta__ = {
    "id": "ma_120",
    "nickname": "MA120 Direction",
    "category": "technical",
    "description": "MA120中长期方向 — 价格站上MA120且MA120上行=强多头，价格在下方且下行=空头",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 120,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ma120 = ts_mean(close, 120)
    # MA120 近 5 日斜率（上行/下行）
    slope = ma120 - ma120.shift(5)
    valid = ma120.notna() & slope.notna()
    above = ((close > ma120) & valid).astype(float)
    rising = ((slope > 0) & valid).astype(float)
    # 位置 60% + 斜率方向 40%
    score = (above * 0.6 + rising * 0.4) * 100.0
    # 数据不足窗口时取中性 50，避免前段误导性极值
    return score.where(valid, 50.0).clip(0, 100)
