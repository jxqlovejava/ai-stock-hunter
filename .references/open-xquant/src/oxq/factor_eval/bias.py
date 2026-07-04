"""Lookahead bias detection for factor evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def detect_lookahead_bias(
    factor_values: pd.Series,
    prices: pd.DataFrame,
    threshold: float = 0.5,
) -> dict:
    """Detect potential lookahead bias by correlating factor with current-period returns.

    A high correlation between factor values and same-period returns suggests
    the factor may be using future information.

    Parameters
    ----------
    factor_values
        Series with MultiIndex (date, asset).
    prices
        Close prices DataFrame.
    threshold
        Absolute correlation above this triggers a warning. Default 0.5.

    Returns
    -------
    dict with correlation, has_warning, message.
    """
    dates = factor_values.index.get_level_values("date")
    assets = factor_values.index.get_level_values("asset")

    current_returns = prices.pct_change()

    f_vals = []
    r_vals = []

    for date, asset, fval in zip(dates, assets, factor_values.values):
        if asset not in current_returns.columns or date not in current_returns.index:
            continue
        ret = current_returns.loc[date, asset]
        if np.isnan(fval) or np.isnan(ret):
            continue
        f_vals.append(fval)
        r_vals.append(ret)

    if len(f_vals) < 3:
        return {
            "correlation": float("nan"),
            "has_warning": False,
            "message": None,
        }

    corr, _ = stats.pearsonr(f_vals, r_vals)
    corr = float(corr)
    has_warning = abs(corr) > threshold

    message = None
    if has_warning:
        message = (
            f"Possible lookahead bias detected: factor-to-current-return "
            f"correlation = {corr:.4f} (threshold: {threshold}). "
            f"Please verify that factor values do not use future information."
        )

    return {
        "correlation": corr,
        "has_warning": has_warning,
        "message": message,
    }
