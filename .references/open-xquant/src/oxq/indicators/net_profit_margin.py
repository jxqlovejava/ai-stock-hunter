"""NetProfitMargin indicator — computes net_income / revenue."""

from __future__ import annotations

import numpy as np
import pandas as pd


class NetProfitMargin:
    """Net profit margin: net_income / revenue."""

    name = "NetProfitMargin"
    formula = r"NetProfitMargin = \frac{NetIncome}{Revenue}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        income_col: str = "net_income",
        revenue_col: str = "revenue",
    ) -> pd.Series:
        """Return net profit margin; NaN where revenue is 0 or NaN."""
        revenue = mktdata[revenue_col].replace(0, np.nan)
        return mktdata[income_col] / revenue
