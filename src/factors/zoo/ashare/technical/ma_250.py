# -*- coding: utf-8 -*-
"""MA250 中长期方向 — 价格相对 MA250 位置 + MA250 斜率。

MA250 为年线，是 A 股「牛熊分界」的常用参考。供 P1-2 中长期方向判断：
价格在年线上方且年线走平/上行 = 牛市格局；跌破年线 = 趋势破坏。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import ts_mean

__alpha_meta__ = {
    "id": "ma_250",
    "nickname": "MA250 Direction",
    "category": "technical",
    "description": "MA250(年线)方向 — 价格站上年线且年线上行=牛市格局，跌破年线=趋势破坏",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 250,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ma250 = ts_mean(close, 250)
    # MA250 近 10 日斜率（年线方向）
    slope = ma250 - ma250.shift(10)
    valid = ma250.notna() & slope.notna()
    above = ((close > ma250) & valid).astype(float)
    rising = ((slope > 0) & valid).astype(float)
    # 位置 60% + 斜率方向 40%
    score = (above * 0.6 + rising * 0.4) * 100.0
    # 数据不足窗口时取中性 50，避免前段误导性极值
    return score.where(valid, 50.0).clip(0, 100)
