"""CashFlowRatio indicator — computes operating_cash_flow / total_assets."""

from __future__ import annotations

import numpy as np
import pandas as pd


class CashFlowRatio:
    """Cash flow ratio: operating_cash_flow / total_assets."""

    name = "CashFlowRatio"
    formula = r"CashFlowRatio = \frac{OCF}{TotalAssets}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        ocf_col: str = "operating_cash_flow",
        assets_col: str = "total_assets",
    ) -> pd.Series:
        """Return cash flow ratio; NaN where total_assets is 0 or NaN."""
        assets = mktdata[assets_col].replace(0, np.nan)
        return mktdata[ocf_col] / assets
