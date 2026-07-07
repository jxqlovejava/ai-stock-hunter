# -*- coding: utf-8 -*-
"""历史波动率百分位 — 波动率在历史中的位置。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import ts_max, ts_min, ts_std

__alpha_meta__ = {
    "id": "hv_percentile",
    "nickname": "HV Percentile",
    "category": "technical",
    "description": "20日年化波动率在252日中的百分位 — 低波动(<30%分位)稳定得分高",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 252,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ret = close.pct_change(1)
    vol20 = ts_std(ret, 20) * np.sqrt(252)  # 年化波动率
    vol_high252 = ts_max(vol20, 252)
    vol_low252 = ts_min(vol20, 252)

    percentile = (vol20 - vol_low252) / (vol_high252 - vol_low252 + 1e-12)

    # 低波动 = 高分
    score = 100.0 * (1.0 - np.clip(percentile, 0, 1))
    return score.clip(lower=0)
