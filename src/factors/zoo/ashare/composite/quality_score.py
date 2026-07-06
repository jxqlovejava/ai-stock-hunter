# -*- coding: utf-8 -*-
"""综合质量得分：应计 (50%) + 盈利质量 (50%)。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank, safe_div

__alpha_meta__ = {
    "id": "quality_score",
    "nickname": "Composite Quality",
    "category": "composite",
    "description": "综合质量得分",
    "columns_required": ["net_profit", "operating_cashflow", "total_assets"],
    "frequency": ["quarterly", "daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    accruals = safe_div(
        panel["net_profit"] - panel["operating_cashflow"],
        panel["total_assets"],
    )
    acc_score = (1.0 - rank(accruals)) * 100.0

    np_clipped = panel["net_profit"].clip(lower=1.0)
    ratio = safe_div(panel["operating_cashflow"], np_clipped).clip(lower=0, upper=5)
    eq_score = rank(ratio) * 100.0

    return acc_score * 0.50 + eq_score * 0.50
