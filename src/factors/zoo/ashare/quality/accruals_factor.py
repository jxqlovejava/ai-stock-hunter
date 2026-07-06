# -*- coding: utf-8 -*-
"""应计利润质量因子。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank, safe_div

__alpha_meta__ = {
    "id": "accruals_factor",
    "nickname": "Low Accruals",
    "category": "quality",
    "description": "低应计利润股票得分高",
    "columns_required": ["net_profit", "operating_cashflow", "total_assets"],
    "frequency": ["quarterly", "daily"],
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    accruals = safe_div(
        panel["net_profit"] - panel["operating_cashflow"],
        panel["total_assets"],
    )
    # 低应计 → 高分
    return (1.0 - rank(accruals)) * 100.0
