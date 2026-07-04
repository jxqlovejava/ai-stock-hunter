"""Factor decay curve -- how predictive power decays over holding periods."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

_MIN_SAMPLE_WARN = 60


def compute_decay_curve(
    factor_values: pd.Series,
    forward_returns_by_period: dict[int, pd.DataFrame],
    periods: list[int] | None = None,
    method: str = "spearman",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Compute factor-return correlation at each forward period.

    Parameters
    ----------
    factor_values
        Series with MultiIndex (date, asset).
    forward_returns_by_period
        {period: DataFrame} from compute_forward_returns.
    periods
        Which periods to evaluate. Defaults to keys of forward_returns_by_period.
    method
        'spearman' (default) or 'pearson'.
    start_date, end_date
        Optional date range filter.

    Returns
    -------
    dict with correlations, half_life, inflection_point,
    recommended_holding, warning.
    """
    if periods is None:
        periods = sorted(forward_returns_by_period.keys())

    dates = factor_values.index.get_level_values("date")
    assets = factor_values.index.get_level_values("asset")

    correlations: dict[int, float] = {}
    min_n = float("inf")

    for p in periods:
        fwd_df = forward_returns_by_period.get(p)
        if fwd_df is None:
            correlations[p] = float("nan")
            continue

        f_vals = []
        r_vals = []
        for date, asset, fval in zip(dates, assets, factor_values.values):
            if start_date and str(date.date()) < start_date:
                continue
            if end_date and str(date.date()) > end_date:
                continue
            if asset not in fwd_df.columns or date not in fwd_df.index:
                continue
            ret = fwd_df.loc[date, asset]
            if np.isnan(fval) or np.isnan(ret):
                continue
            f_vals.append(fval)
            r_vals.append(ret)

        n = len(f_vals)
        min_n = min(min_n, n)

        if n < 3:
            correlations[p] = float("nan")
            continue

        corr_func = stats.spearmanr if method == "spearman" else stats.pearsonr
        corr, _ = corr_func(f_vals, r_vals)
        correlations[p] = float(corr)

    # Half-life: when correlation drops to 50% of first period's value
    half_life = _compute_half_life(periods, correlations)

    # Inflection point: two consecutive drops > 20% of initial value
    inflection = _compute_inflection(periods, correlations)

    warning = None
    if min_n == float("inf"):
        min_n = 0
    if min_n < _MIN_SAMPLE_WARN:
        warning = f"Min sample size {int(min_n)} < {_MIN_SAMPLE_WARN}, results for reference only."

    return {
        "correlations": correlations,
        "half_life": half_life,
        "inflection_point": inflection,
        "recommended_holding": inflection,
        "warning": warning,
    }


def _compute_half_life(
    periods: list[int],
    correlations: dict[int, float],
) -> int | None:
    """Find period where |correlation| drops below 50% of first period."""
    sorted_p = sorted(periods)
    first_corr = correlations.get(sorted_p[0], float("nan"))
    if np.isnan(first_corr) or abs(first_corr) < 1e-12:
        return None
    threshold = abs(first_corr) * 0.5
    for p in sorted_p[1:]:
        c = correlations.get(p, float("nan"))
        if np.isnan(c):
            continue
        if abs(c) <= threshold:
            return p
    return None


def _compute_inflection(
    periods: list[int],
    correlations: dict[int, float],
) -> int | None:
    """Find inflection: two consecutive drops > 20% of initial |correlation|."""
    sorted_p = sorted(periods)
    if len(sorted_p) < 3:
        return None
    first_corr = correlations.get(sorted_p[0], float("nan"))
    if np.isnan(first_corr) or abs(first_corr) < 1e-12:
        return None
    drop_threshold = abs(first_corr) * 0.20

    for i in range(1, len(sorted_p) - 1):
        c_prev = correlations.get(sorted_p[i - 1], float("nan"))
        c_curr = correlations.get(sorted_p[i], float("nan"))
        c_next = correlations.get(sorted_p[i + 1], float("nan"))
        if np.isnan(c_prev) or np.isnan(c_curr) or np.isnan(c_next):
            continue
        drop1 = abs(c_prev) - abs(c_curr)
        drop2 = abs(c_curr) - abs(c_next)
        if drop1 > drop_threshold and drop2 > drop_threshold:
            return sorted_p[i]
    return None
