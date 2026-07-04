"""Crossover signal — detects when a fast line crosses above a slow line."""

from __future__ import annotations

import pandas as pd


class Crossover:
    """Detect upward crossover between two indicator columns.

    Produces ``True`` on bars where *fast* crosses above *slow*
    (i.e. previous bar fast <= slow, current bar fast > slow).
    """

    name = "Crossover"

    def compute(
        self,
        mktdata: pd.DataFrame,
        fast: str = "",
        slow: str = "",
    ) -> pd.Series:
        """Return cross-up boolean series for the given *mktdata*."""
        f = mktdata[fast]
        s = mktdata[slow]
        return (f.shift(1) <= s.shift(1)) & (f > s)
