"""MarketCap indicator — computes close * total_shares."""

from __future__ import annotations

import pandas as pd


class MarketCap:
    """Element-wise market capitalisation: close * total_shares."""

    name = "MarketCap"
    formula = r"MarketCap = Close \times TotalShares"

    def compute(
        self,
        mktdata: pd.DataFrame,
        price_col: str = "close",
        shares_col: str = "total_shares",
    ) -> pd.Series:
        """Return element-wise close * total_shares."""
        return mktdata[price_col] * mktdata[shares_col]
