"""Cash period value analysis for time-series factor evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd

_MIN_SAMPLE_WARN = 60


def compute_cash_period_value(
    factor_values: pd.Series,
    forward_returns: pd.DataFrame,
    signal_threshold: float = 0.0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Analyze returns during holding vs cash periods.

    Holding: factor > threshold. Cash: factor <= threshold.

    Returns dict with holding_avg_return, cash_avg_return, return_spread,
    cash_max_loss, holding_ratio, cash_ratio, holding_count, cash_count,
    total_count, warning.
    """
    dates = factor_values.index.get_level_values("date")
    assets = factor_values.index.get_level_values("asset")

    factors = []
    returns = []

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

    factors_arr = np.array(factors)
    returns_arr = np.array(returns)
    n = len(factors_arr)

    warning = None
    if n < _MIN_SAMPLE_WARN:
        warning = f"Sample size {n} < {_MIN_SAMPLE_WARN}, results for reference only."

    if n == 0:
        return {
            "holding_avg_return": float("nan"),
            "cash_avg_return": float("nan"),
            "return_spread": float("nan"),
            "cash_max_loss": float("nan"),
            "holding_ratio": float("nan"),
            "cash_ratio": float("nan"),
            "holding_count": 0,
            "cash_count": 0,
            "total_count": 0,
            "warning": warning,
        }

    holding_mask = factors_arr > signal_threshold
    cash_mask = ~holding_mask

    holding_returns = returns_arr[holding_mask]
    cash_returns = returns_arr[cash_mask]

    holding_avg = float(np.mean(holding_returns)) if len(holding_returns) > 0 else float("nan")
    cash_avg = float(np.mean(cash_returns)) if len(cash_returns) > 0 else float("nan")

    if np.isnan(holding_avg) or np.isnan(cash_avg):
        spread = float("nan")
    else:
        spread = holding_avg - cash_avg

    cash_max_loss = float(np.min(cash_returns)) if len(cash_returns) > 0 else float("nan")

    holding_count = int(np.sum(holding_mask))
    cash_count = int(np.sum(cash_mask))

    return {
        "holding_avg_return": holding_avg,
        "cash_avg_return": cash_avg,
        "return_spread": spread,
        "cash_max_loss": cash_max_loss,
        "holding_ratio": holding_count / n,
        "cash_ratio": cash_count / n,
        "holding_count": holding_count,
        "cash_count": cash_count,
        "total_count": n,
        "warning": warning,
    }
