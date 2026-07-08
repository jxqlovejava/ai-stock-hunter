# -*- coding: utf-8 -*-
"""资金背离风险 — 价格与主力资金方向一致=安全，背离=风险。"""

from __future__ import annotations

import numpy as np
import pandas as pd

__alpha_meta__ = {
    "id": "fund_divergence_risk",
    "nickname": "Fund Divergence Risk",
    "category": "flow",
    "description": "资金背离风险 — 价格与主力资金方向一致=安全，背离=风险",
    "columns_required": ["close", "main_net_inflow"],
    "frequency": ["daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if "close" not in panel or "main_net_inflow" not in panel:
        idx = list(panel.values())[0].index
        cols = list(panel.values())[0].columns
        return pd.DataFrame(50.0, index=idx[-1:], columns=cols)

    close = panel["close"]
    main_net = panel["main_net_inflow"]

    # 价格变动方向：当日收盘 > 前日收盘
    price_up = close > close.shift(1)
    price_down = close < close.shift(1)

    # 主力资金方向：净流入 > 0
    fund_in = main_net > 0
    fund_out = main_net < 0

    # 默认给 50 分（中性）
    score = pd.DataFrame(50.0, index=close.index, columns=close.columns)

    # 一致看多：价格涨 + 主力净流入 → 80
    mask_bull_confirm = price_up & fund_in
    score[mask_bull_confirm] = 80.0

    # 一致看空：价格跌 + 主力净流出 → 70
    mask_bear_confirm = price_down & fund_out
    score[mask_bear_confirm] = 70.0

    # 背离：价格涨 + 主力净流出 → 多头陷阱，30
    mask_bull_trap = price_up & fund_out
    score[mask_bull_trap] = 30.0

    # 背离：价格跌 + 主力净流入 → 空头陷阱，40
    mask_bear_trap = price_down & fund_in
    score[mask_bear_trap] = 40.0

    # 首次行无 shift 值 → NaN，用中性填充
    score = score.fillna(50.0)
    return score.clip(lower=0, upper=100)
