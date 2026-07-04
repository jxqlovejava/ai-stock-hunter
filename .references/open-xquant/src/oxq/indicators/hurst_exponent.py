"""HurstExponent indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd


class HurstExponent:
    """Rolling Hurst exponent via the Rescaled Range (R/S) method.

    H = log(R/S) / log(n)

    where R is the range of cumulative deviations from the mean and S is the
    standard deviation of the series.  H > 0.5 indicates trending (persistent)
    behaviour, H < 0.5 indicates mean-reverting (anti-persistent) behaviour,
    and H = 0.5 indicates a random walk.
    """

    name = "HurstExponent"
    formula = r"H = \frac{\log(R/S)}{\log(n)}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        column: str = "close",
        period: int = 20,
    ) -> pd.Series:
        """Return rolling Hurst exponent (first ``period`` values will be NaN)."""
        log_returns = np.log(mktdata[column]).diff()
        result = pd.Series(np.nan, index=mktdata.index)

        for i in range(period, len(mktdata)):
            window = log_returns.iloc[i - period + 1 : i + 1].values
            if np.any(np.isnan(window)):
                continue
            mean = np.mean(window)
            deviations = window - mean
            cumulative = np.cumsum(deviations)
            r = np.max(cumulative) - np.min(cumulative)
            s = np.std(window, ddof=1)
            if s == 0 or r == 0:
                result.iloc[i] = 0.5
                continue
            result.iloc[i] = np.log(r / s) / np.log(period)

        return result
