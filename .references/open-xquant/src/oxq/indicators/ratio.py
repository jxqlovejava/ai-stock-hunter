"""Ratio indicator — computes col_a / col_b."""

from __future__ import annotations

import pandas as pd


class Ratio:
    """Element-wise ratio of two columns: col_a / col_b."""

    name = "Ratio"
    formula = r"Ratio = \frac{A}{B}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        col_a: str = "",
        col_b: str = "",
    ) -> pd.Series:
        """Return element-wise col_a / col_b."""
        return mktdata[col_a] / mktdata[col_b]
