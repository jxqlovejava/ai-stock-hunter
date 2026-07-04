"""PE indicator — computes price / EPS (Price-to-Earnings)."""

from __future__ import annotations

import pandas as pd


class PE:
    """Price-to-Earnings ratio: price / EPS."""

    name = "PE"
    formula = r"PE = \frac{Price}{EPS}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        price_col: str = "close",
        eps_col: str = "eps",
    ) -> pd.Series:
        """Return element-wise price / EPS, NaN where EPS is 0 or NaN."""
        eps = mktdata[eps_col].replace(0, float("nan"))
        return mktdata[price_col] / eps
