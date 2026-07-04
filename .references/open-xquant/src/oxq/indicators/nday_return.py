"""N-day Return indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd


class NdayReturn:
    """N-day cumulative log return: R_N = ln(P_t) - ln(P_{t-N})."""

    name = "NdayReturn"
    formula = r"R_N = \ln P_t - \ln P_{t-N}"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close", period: int = 20,
    ) -> pd.Series:
        """Return N-day log returns (first ``period`` values will be NaN)."""
        log_prices = np.log(mktdata[column])
        return log_prices.diff(period)
