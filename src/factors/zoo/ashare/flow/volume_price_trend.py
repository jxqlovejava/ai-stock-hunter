# -*- coding: utf-8 -*-
"""量价趋势因子 — VPT (Volume Price Trend) 累积资金流。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "volume_price_trend",
    "nickname": "VPT",
    "category": "flow",
    "description": "成交量×价格变化的累积→资金流入趋势；高VPT=资金持续流入",
    "columns_required": ["close", "volume"],
    "frequency": ["daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    vol = panel["volume"]
    # VPT_i = VPT_{i-1} + volume_i * (close_i - close_{i-1}) / close_{i-1}
    ret = close.pct_change()
    daily_flow = vol * ret.fillna(0.0)
    vpt = daily_flow.cumsum()
    # 标准化到 0-100 截面排名
    return rank(vpt) * 100.0
