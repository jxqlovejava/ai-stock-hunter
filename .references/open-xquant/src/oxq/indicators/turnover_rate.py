"""TurnoverRate indicator — computes volume / total_shares."""

from __future__ import annotations

import numpy as np
import pandas as pd


class TurnoverRate:
    """Element-wise turnover rate: volume / total_shares."""

    name = "TurnoverRate"
    formula = r"TurnoverRate = \frac{Volume}{TotalShares}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        volume_col: str = "volume",
        shares_col: str = "total_shares",
    ) -> pd.Series:
        """Return element-wise volume / total_shares.

        NaN where total_shares is 0 or missing.
        """
        volume = mktdata[volume_col]
        shares = mktdata[shares_col].replace(0, np.nan)
        return volume / shares
