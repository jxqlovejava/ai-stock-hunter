# -*- coding: utf-8 -*-
"""均线交叉信号 — MA5/MA20 金叉死叉检测。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, ts_mean

__alpha_meta__ = {
    "id": "ma_cross",
    "nickname": "MA Cross",
    "category": "technical",
    "description": "MA5上穿MA20金叉强度 — 金叉当日+前日距离越大信号越强，死叉得分低",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 21,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ma5 = ts_mean(close, 5)
    ma20 = ts_mean(close, 20)

    # 当日距离 + 金叉检测
    distance = (ma5 - ma20) / (ma20 + 1e-12)  # 乖离率
    crossed_up = (ma5 > ma20) & (ma5.shift(1) <= ma20.shift(1))
    crossed_down = (ma5 < ma20) & (ma5.shift(1) >= ma20.shift(1))

    # 金叉加分，死叉减分，乖离率放大
    score = distance * 100.0
    score = score + crossed_up.astype(float) * 15.0
    score = score - crossed_down.astype(float) * 15.0

    return rank(score) * 100.0
