"""EP indicator — computes EPS / price (Earnings-to-Price)."""

from __future__ import annotations

import pandas as pd


class EP:
    """Earnings-to-Price ratio: EPS / price."""

    name = "EP"
    formula = r"EP = \frac{EPS}{Price}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        eps_col: str = "eps",
        price_col: str = "close",
    ) -> pd.Series:
        """Return element-wise EPS / price, NaN where price is 0 or NaN."""
        price = mktdata[price_col].replace(0, float("nan"))
        return mktdata[eps_col] / price
