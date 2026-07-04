"""BP indicator — computes book_value_per_share / price (Book-to-Price)."""

from __future__ import annotations

import pandas as pd


class BP:
    """Book-to-Price ratio: book_value_per_share / price."""

    name = "BP"
    formula = r"BP = \frac{BVPS}{Price}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        bvps_col: str = "book_value_per_share",
        price_col: str = "close",
    ) -> pd.Series:
        """Return element-wise BVPS / price, NaN where price is 0 or NaN."""
        price = mktdata[price_col].replace(0, float("nan"))
        return mktdata[bvps_col] / price
