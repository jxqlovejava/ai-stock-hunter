# -*- coding: utf-8 -*-
"""MACD 柱状图动能方向 — 柱状放大/收窄布尔位（供结构化快照）。

P1-2 MACD 定动能：柱状图放大（hist > 前日）表示动能增强，收窄表示动能衰减。
输出为布尔位帧：放大 = 100（动能增强），收窄 = 0（动能衰减）。
与 macd_histogram.py（归一化 rank 单值）互补，供双层过滤与结构化快照消费。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__alpha_meta__ = {
    "id": "macd_hist_rising",
    "nickname": "MACD Hist Rising",
    "category": "technical",
    "description": "MACD柱状图动能方向 — 柱状放大=100(动能增强)，收窄=0(动能衰减)，供双层过滤与结构化快照",
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
    hist = (dif - dea) * 2.0
    rising = hist > hist.shift(1)
    # 布尔位: 放大=100(动能增强)，收窄=0(动能衰减)
    return rising.fillna(False).astype(float) * 100.0
