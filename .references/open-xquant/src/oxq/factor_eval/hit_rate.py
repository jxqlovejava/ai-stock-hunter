"""Hit rate computation for time-series factor evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd

_MIN_SAMPLE_WARN = 60


def compute_hit_rate(
    factor_values: pd.Series,
    forward_returns: pd.DataFrame,
    signal_threshold: float = 0.0,
    exclude_limit_days: bool = False,
    limit_days: pd.DataFrame | None = None,
    rolling_window: int = 60,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Compute hit rate metrics for a time-series factor.

    Parameters
    ----------
    factor_values
        Series with MultiIndex (date, asset).
    forward_returns
        DataFrame with index=date, columns=asset.
    signal_threshold
        Factor value threshold for generating signals. Default 0.
    exclude_limit_days
        If True, exclude limit-up/down days from calculation.
    limit_days
        Boolean DataFrame marking limit days.
    rolling_window
        Window size for rolling hit rate.
    start_date, end_date
        Optional date range filter.

    Returns
    -------
    dict with total_hit_rate, long_hit_rate, short_hit_rate,
    rolling_hit_rate (Series), sample_count, warning.
    """
    # Build aligned Series of (factor, return) pairs
    dates = factor_values.index.get_level_values("date")
    assets = factor_values.index.get_level_values("asset")

    factors = []
    returns = []
    ret_dates = []

    for date, asset, fval in zip(dates, assets, factor_values.values):
        if start_date and str(date.date()) < start_date:
            continue
        if end_date and str(date.date()) > end_date:
            continue
        if asset not in forward_returns.columns:
            continue
        if date not in forward_returns.index:
            continue

        ret = forward_returns.loc[date, asset]
        if np.isnan(ret) or np.isnan(fval):
            continue

        if exclude_limit_days and limit_days is not None:
            if asset in limit_days.columns and limit_days.loc[date, asset]:
                continue

        factors.append(fval)
        returns.append(ret)
        ret_dates.append(date)

    factors_arr = np.array(factors)
    returns_arr = np.array(returns)
    n = len(factors_arr)

    warning = None
    if n < _MIN_SAMPLE_WARN:
        warning = f"Sample size {n} < {_MIN_SAMPLE_WARN}, results for reference only."

    if n == 0:
        return {
            "total_hit_rate": float("nan"),
            "long_hit_rate": float("nan"),
            "short_hit_rate": float("nan"),
            "rolling_hit_rate": pd.Series(dtype=float),
            "sample_count": 0,
            "warning": warning,
        }

    # Long: factor > threshold AND return > 0
    long_mask = factors_arr > signal_threshold
    short_mask = factors_arr < signal_threshold

    long_hits = np.sum((long_mask) & (returns_arr > 0))
    long_total = np.sum(long_mask)
    long_hit_rate = float(long_hits / long_total) if long_total > 0 else float("nan")

    short_hits = np.sum((short_mask) & (returns_arr < 0))
    short_total = np.sum(short_mask)
    short_hit_rate = float(short_hits / short_total) if short_total > 0 else float("nan")

    total_hits = long_hits + short_hits
    signal_count = long_total + short_total
    total_hit_rate = float(total_hits / signal_count) if signal_count > 0 else float("nan")

    # Rolling hit rate
    hit_flags = pd.Series(
        ((long_mask & (returns_arr > 0)) | (short_mask & (returns_arr < 0))).astype(
            float
        ),
        index=ret_dates,
    )
    rolling = hit_flags.rolling(window=rolling_window, min_periods=1).mean()

    return {
        "total_hit_rate": total_hit_rate,
        "long_hit_rate": long_hit_rate,
        "short_hit_rate": short_hit_rate,
        "rolling_hit_rate": rolling,
        "sample_count": n,
        "warning": warning,
    }
