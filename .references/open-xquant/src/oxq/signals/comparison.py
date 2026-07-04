"""Comparison signal — fires when one column satisfies a relationship with another."""

from __future__ import annotations

import pandas as pd

from oxq.signals._ops import resolve_op


class Comparison:
    """True when ``left`` column satisfies ``relationship`` relative to ``right`` column."""

    name = "Comparison"

    def compute(
        self,
        mktdata: pd.DataFrame,
        left: str = "",
        right: str = "",
        relationship: str = "gt",
    ) -> pd.Series:
        op = resolve_op(relationship)
        return op(mktdata[left], mktdata[right])
