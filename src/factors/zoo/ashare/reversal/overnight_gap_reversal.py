# -*- coding: utf-8 -*-
"""隔夜跳空反转因子 — A 股隔夜高开缺口常回补。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "overnight_gap_reversal",
    "nickname": "Overnight Gap Reversal",
    "category": "reversal",
    "description": "隔夜跳空缺口越大→回补概率越高；高开=低分，低开=高分",
    "columns_required": ["open", "close"],
    "frequency": ["daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    open_p = panel["open"]
    close = panel["close"]
    prev_close = close.shift(1)
    # 隔夜缺口 = (open - prev_close) / prev_close
    gap = (open_p - prev_close) / (prev_close + 1e-9)
    # 正缺口（高开）= 低分（易回补下跌）；负缺口（低开）= 高分（易回补上涨）
    return (1.0 - rank(gap)) * 100.0
