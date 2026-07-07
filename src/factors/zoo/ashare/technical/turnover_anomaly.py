# -*- coding: utf-8 -*-
"""换手率异常 — 筹码活跃度偏离度。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import safe_div, ts_mean

__alpha_meta__ = {
    "id": "turnover_anomaly",
    "nickname": "Turnover Anomaly",
    "category": "technical",
    "description": "换手率/20日均值 — 1.2倍最优(温和活跃)，>3倍过度换手(筹码松动预警)，<0.3无人关注",
    "columns_required": ["turnover"],
    "frequency": ["daily"],
    "min_warmup_bars": 21,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if "turnover" not in panel:
        idx = list(panel.values())[0].index
        cols = list(panel.values())[0].columns
        return pd.DataFrame(50.0, index=idx[-1:], columns=cols)

    turnover = panel["turnover"]
    avg_turnover = ts_mean(turnover, 20)
    ratio = safe_div(turnover, avg_turnover)
    deviation = np.abs(ratio - 1.2) / 1.2
    score = 100.0 * np.exp(-deviation * 2.5)
    return score.clip(lower=0)
