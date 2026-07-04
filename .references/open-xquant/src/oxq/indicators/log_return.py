"""Log Return indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd


class LogReturn:
    """Daily log return: r_t = ln(P_t) - ln(P_{t-1})."""

    name = "LogReturn"
    formula = r"r_t = \ln P_t - \ln P_{t-1}"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close",
    ) -> pd.Series:
        """Return log returns (first value will be NaN)."""
        return np.log(mktdata[column]).diff()
