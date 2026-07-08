# -*- coding: utf-8 -*-
"""盈利动量因子 — 净利润增速趋势（增速加速=高分）。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "earnings_momentum",
    "nickname": "Earnings Momentum",
    "category": "expectation",
    "description": "净利润增速的加速度→增速在加快的股票得分高",
    "columns_required": ["earnings_growth", "revenue_growth"],
    "frequency": ["quarterly"],
    "provider_confidence": 0.70,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    # 盈利增速 0.7 + 营收增速 0.3 的加权
    eg = panel.get("earnings_growth", panel.get("revenue_growth"))
    if eg is None:
        # fallback: 只用 revenue_growth
        rg = panel["revenue_growth"]
        return rank(rg) * 100.0

    rg = panel.get("revenue_growth", eg)
    composite = eg * 0.7 + rg * 0.3
    return rank(composite) * 100.0
