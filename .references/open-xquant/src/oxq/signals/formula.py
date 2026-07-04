"""Formula signal — boolean expression evaluated on DataFrame columns."""

from __future__ import annotations

import pandas as pd


class Formula:
    """True where ``expr`` evaluates to True.  Uses ``pd.DataFrame.eval()``."""

    name = "Formula"

    def compute(
        self,
        mktdata: pd.DataFrame,
        expr: str = "",
    ) -> pd.Series:
        return mktdata.eval(expr).astype(bool)
