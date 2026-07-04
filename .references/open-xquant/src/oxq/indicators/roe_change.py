"""ROEChange indicator — computes first-order difference of ROE."""

from __future__ import annotations

import pandas as pd


class ROEChange:
    """ROE change: roe_t - roe_{t-1} (first-order difference)."""

    name = "ROEChange"
    formula = r"ROEChange = ROE_t - ROE_{t-1}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        roe_col: str = "roe",
        period: int = 1,
    ) -> pd.Series:
        """Return first-order difference of ROE; first `period` values are NaN."""
        return mktdata[roe_col].diff(periods=period)
