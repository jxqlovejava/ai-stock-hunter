"""Rolling Maximum Drawdown indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd


class RollingMDD:
    """N-day rolling maximum drawdown.

    For each window, computes the largest peak-to-trough decline
    in log-price space. Returns negative values (e.g. -0.10 = -10%).
    """

    name = "RollingMDD"
    formula = r"MDD_N = \min_{i \in [t-N+1,t]}\left(\ln P_i - \max_{j \leq i} \ln P_j\right)"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close", period: int = 20,
    ) -> pd.Series:
        """Return rolling max drawdown as negative fractions."""
        log_prices = np.log(mktdata[column])

        def _mdd(window: np.ndarray) -> float:
            peak = np.maximum.accumulate(window)
            dd = window - peak
            return float(np.min(dd))

        return log_prices.rolling(period).apply(_mdd, raw=True)
