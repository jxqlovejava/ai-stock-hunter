"""Timestamp signal — time-based triggers (month start, quarter end, weekday)."""

from __future__ import annotations

import pandas as pd


class Timestamp:
    """True on dates matching ``rule``.

    Supported rules:
    - ``month_start`` / ``month_end`` — first/last trading day of month
    - ``quarter_start`` / ``quarter_end`` — first/last trading day of quarter
    - ``weekday:N`` — every weekday N (0=Monday … 4=Friday)
    """

    name = "Timestamp"

    def compute(
        self,
        mktdata: pd.DataFrame,
        rule: str = "",
    ) -> pd.Series:
        idx = mktdata.index
        months = pd.Series(idx.month, index=idx)
        quarters = pd.Series(idx.quarter, index=idx)

        if rule == "month_start":
            series = months != months.shift(1)
        elif rule == "month_end":
            series = months != months.shift(-1)
        elif rule == "quarter_start":
            series = quarters != quarters.shift(1)
        elif rule == "quarter_end":
            series = quarters != quarters.shift(-1)
        elif rule.startswith("weekday:"):
            day = int(rule.split(":")[1])
            series = pd.Series(idx.weekday == day, index=idx)
        else:
            series = pd.Series(False, index=idx)

        return series.fillna(True).astype(bool)
