"""Momentum indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd


class Momentum:
    """N-day momentum (average daily log return over N days).

    Momentum_N = (ln(P_t) - ln(P_{t-N})) / N
    """

    name = "Momentum"
    formula = r"Mom_N = \frac{\ln P_t - \ln P_{t-N}}{N}"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close", period: int = 20,
    ) -> pd.Series:
        """Return N-day momentum (first ``period`` values will be NaN)."""
        log_prices = np.log(mktdata[column])
        return log_prices.diff(period) / period
