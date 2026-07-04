"""Threshold signal — fires when a column crosses above or below a value."""

from __future__ import annotations

import pandas as pd

from oxq.signals._ops import resolve_op


class Threshold:
    """True when ``column`` satisfies ``relationship`` relative to ``threshold``."""

    name = "Threshold"

    def compute(
        self,
        mktdata: pd.DataFrame,
        column: str = "",
        threshold: float = 0.0,
        relationship: str = "gt",
    ) -> pd.Series:
        op = resolve_op(relationship)
        return op(mktdata[column], threshold)
