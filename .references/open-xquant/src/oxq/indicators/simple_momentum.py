"""SimpleMomentum indicator — simple return normalized by period."""

from __future__ import annotations

import pandas as pd


class SimpleMomentum:
    """N-day momentum using simple returns.

    SimpleMomentum_N = (P_t / P_{t-N} - 1) / N
    """

    name = "SimpleMomentum"
    formula = r"Mom_N = \frac{P_t / P_{t-N} - 1}{N}"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close", period: int = 20,
    ) -> pd.Series:
        """Return N-day simple momentum (first ``period`` values will be NaN)."""
        prices = mktdata[column]
        return (prices / prices.shift(period) - 1) / period
