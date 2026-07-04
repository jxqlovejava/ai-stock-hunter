"""PB indicator — computes price / book_value_per_share (Price-to-Book)."""

from __future__ import annotations

import pandas as pd


class PB:
    """Price-to-Book ratio: price / book_value_per_share."""

    name = "PB"
    formula = r"PB = \frac{Price}{BVPS}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        price_col: str = "close",
        bvps_col: str = "book_value_per_share",
    ) -> pd.Series:
        """Return element-wise price / BVPS, NaN where BVPS is 0 or NaN."""
        bvps = mktdata[bvps_col].replace(0, float("nan"))
        return mktdata[price_col] / bvps
