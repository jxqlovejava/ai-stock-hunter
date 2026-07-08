# -*- coding: utf-8 -*-
"""月度反转因子 — 过去20日跌得多的股票未来可能反弹（A股反转效应）。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "monthly_reversal",
    "nickname": "Monthly Reversal",
    "category": "reversal",
    "description": "过去20日收益越低→未来反弹概率越大→得分越高",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ret_20 = close.pct_change(20)
    # 低收益 = 高分（反转）
    return (1.0 - rank(ret_20)) * 100.0
