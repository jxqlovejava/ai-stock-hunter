"""AccrualRatio indicator — computes (net_income - operating_cash_flow) / total_assets."""

from __future__ import annotations

import numpy as np
import pandas as pd


class AccrualRatio:
    """Accrual ratio: (net_income - operating_cash_flow) / total_assets."""

    name = "AccrualRatio"
    formula = r"AccrualRatio = \frac{NetIncome - OCF}{TotalAssets}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        income_col: str = "net_income",
        ocf_col: str = "operating_cash_flow",
        assets_col: str = "total_assets",
    ) -> pd.Series:
        """Return accrual ratio; NaN where total_assets is 0 or NaN."""
        assets = mktdata[assets_col].replace(0, np.nan)
        return (mktdata[income_col] - mktdata[ocf_col]) / assets
