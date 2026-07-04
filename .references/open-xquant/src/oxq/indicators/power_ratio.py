"""PowerRatio indicator — col_a / col_b ^ exponent."""

from __future__ import annotations

import pandas as pd


class PowerRatio:
    """Ratio with power adjustment: col_a / col_b ^ exponent.

    When exponent=0.5, this computes col_a / sqrt(col_b),
    equivalent to xquant's vol_penalty=0.5 behavior.
    """

    name = "PowerRatio"
    formula = r"PowerRatio = \frac{A}{B^{exp}}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        col_a: str = "",
        col_b: str = "",
        exponent: float = 1.0,
    ) -> pd.Series:
        """Return element-wise col_a / col_b^exponent."""
        return mktdata[col_a] / (mktdata[col_b] ** exponent)
