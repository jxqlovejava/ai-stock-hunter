"""Profit/loss ratio computation for time-series factor evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd

_MIN_SAMPLE_WARN = 60


def compute_profit_loss_ratio(
    factor_values: pd.Series,
    forward_returns: pd.DataFrame,
    signal_threshold: float = 0.0,
    rolling_window: int = 60,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Compute profit/loss ratio for long signals.

    Returns dict with avg_win, avg_loss, ratio, rolling_ratio (Series),
    return_distribution (list), sample_count, warning.
    """
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
        if asset not in forward_returns.columns or date not in forward_returns.index:
            continue
        ret = forward_returns.loc[date, asset]
        if np.isnan(fval) or np.isnan(ret):
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

    long_mask = factors_arr > signal_threshold
    long_returns = returns_arr[long_mask]
    long_count = len(long_returns)

    if long_count == 0:
        return {
            "avg_win": float("nan"),
            "avg_loss": float("nan"),
            "ratio": float("nan"),
            "rolling_ratio": pd.Series(dtype=float),
            "return_distribution": [],
            "sample_count": 0,
            "warning": warning,
        }

    wins = long_returns[long_returns > 0]
    losses = long_returns[long_returns < 0]

    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.0

    if avg_loss == 0.0:
        ratio = float("inf") if avg_win > 0 else float("nan")
    else:
        ratio = avg_win / avg_loss

    # Rolling P/L ratio
    idx = range(len(returns_arr))
    long_ret_series = pd.Series(returns_arr, index=idx)
    long_flag_arr = long_mask.astype(float)

    def _rolling_pl(window: pd.Series) -> float:
        rets = window.values
        flags = long_flag_arr[window.index]
        masked = rets[flags > 0]
        if len(masked) == 0:
            return float("nan")
        w = masked[masked > 0]
        l_arr = masked[masked < 0]
        aw = float(np.mean(w)) if len(w) > 0 else 0.0
        al = float(np.mean(np.abs(l_arr))) if len(l_arr) > 0 else 0.0
        if al == 0.0:
            return float("inf") if aw > 0 else float("nan")
        return aw / al

    rolling_ratio = long_ret_series.rolling(
        window=rolling_window,
        min_periods=1,
    ).apply(_rolling_pl, raw=False)

    return {
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "ratio": ratio,
        "rolling_ratio": rolling_ratio,
        "return_distribution": long_returns.tolist(),
        "sample_count": long_count,
        "warning": warning,
    }
