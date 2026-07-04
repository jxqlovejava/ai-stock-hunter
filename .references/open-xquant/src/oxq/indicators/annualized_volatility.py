"""AnnualizedVolatility indicator — population stddev of simple returns, annualized."""

from __future__ import annotations

import numpy as np
import pandas as pd


class AnnualizedVolatility:
    """Rolling annualized volatility of simple returns.

    vol = pstdev(simple_returns, period) * sqrt(252)

    Uses population standard deviation (ddof=0) to match xquant reference.
    """

    name = "AnnualizedVolatility"
    formula = r"\sigma = \text{pstdev}(r_{\text{simple}}) \times \sqrt{252}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        column: str = "close",
        period: int = 20,
    ) -> pd.Series:
        """Return rolling annualized volatility (population stddev)."""
        simple_returns = mktdata[column].pct_change()
        return simple_returns.rolling(period).std(ddof=0) * np.sqrt(252)
