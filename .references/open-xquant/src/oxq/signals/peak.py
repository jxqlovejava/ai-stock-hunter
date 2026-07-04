"""Peak signal — detect local peaks and troughs."""

from __future__ import annotations

import pandas as pd


class Peak:
    """True at local peaks (``kind='peak'``) or troughs (``kind='trough'``).

    A peak of ``order`` N requires the value to be strictly greater than
    the N neighbours on each side.  Points within ``order`` of the edges
    are always False (insufficient context).
    """

    name = "Peak"

    def compute(
        self,
        mktdata: pd.DataFrame,
        column: str = "",
        kind: str = "peak",
        order: int = 1,
    ) -> pd.Series:
        is_max = kind == "peak"
        col = mktdata[column]
        cond = pd.Series(True, index=col.index)
        for i in range(1, order + 1):
            if is_max:
                cond = cond & (col > col.shift(i)) & (col > col.shift(-i))
            else:
                cond = cond & (col < col.shift(i)) & (col < col.shift(-i))
        return cond.fillna(False).astype(bool)
