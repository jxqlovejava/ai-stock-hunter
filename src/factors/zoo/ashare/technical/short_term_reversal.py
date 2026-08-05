# -*- coding: utf-8 -*-
"""短期反转 — 5 日收益率反转效应。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import cross_or_ts_rank

__alpha_meta__ = {
    "id": "short_term_reversal",
    "nickname": "Short-Term Reversal",
    "category": "technical",
    "description": "5日收益率反转 — 急跌后反弹概率↑(高分)，急涨后回调概率↑(低分)",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 6,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ret_5d = close.pct_change(5)
    # 单列面板走时序 rank（当前值 vs 自身 20 根历史），多列保持截面 rank
    return cross_or_ts_rank(-ret_5d, n=20) * 100.0
