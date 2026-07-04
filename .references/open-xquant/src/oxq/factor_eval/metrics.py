"""Pure functions for factor evaluation metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def compute_ic(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    min_obs: int = 3,
) -> dict[str, object]:
    """Compute Information Coefficient (mean per-period Pearson correlation).

    Parameters
    ----------
    factor : pd.DataFrame
        Factor values. index=date, columns=symbols.
    forward_returns : pd.DataFrame
        Forward returns aligned with factor. Same shape.
    min_obs : int
        Minimum observations per period. Periods with fewer are skipped.

    Returns
    -------
    dict with keys: mean, std, series (per-period IC values as list).
    """
    ic_values: list[float] = []
    for date in factor.index:
        f = factor.loc[date]
        r = forward_returns.loc[date]
        mask = f.notna() & r.notna()
        if mask.sum() < min_obs:
            continue
        corr, _ = stats.pearsonr(f[mask], r[mask])
        ic_values.append(float(corr))

    if not ic_values:
        return {"mean": float("nan"), "std": float("nan"), "series": []}

    return {
        "mean": float(np.mean(ic_values)),
        "std": float(np.std(ic_values, ddof=1)),
        "series": ic_values,
    }


def compute_rank_ic(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    min_obs: int = 3,
) -> dict[str, object]:
    """Compute Rank IC (mean per-period Spearman rank correlation)."""
    ic_values: list[float] = []
    for date in factor.index:
        f = factor.loc[date]
        r = forward_returns.loc[date]
        mask = f.notna() & r.notna()
        if mask.sum() < min_obs:
            continue
        corr, _ = stats.spearmanr(f[mask], r[mask])
        ic_values.append(float(corr))

    if not ic_values:
        return {"mean": float("nan"), "std": float("nan"), "series": []}

    return {
        "mean": float(np.mean(ic_values)),
        "std": float(np.std(ic_values, ddof=1)),
        "series": ic_values,
    }


def compute_icir(ic_mean: float, ic_std: float) -> float:
    """Compute ICIR = IC mean / IC std."""
    if ic_std == 0.0 or np.isnan(ic_mean) or np.isnan(ic_std):
        return float("nan")
    return ic_mean / ic_std


def compute_decay(
    factor: pd.DataFrame,
    prices: pd.DataFrame,
    horizons: list[int],
    min_obs: int = 3,
) -> dict[str, object]:
    """Compute IC at multiple forward return horizons.

    Parameters
    ----------
    factor : pd.DataFrame
        Factor values. index=date, columns=symbols.
    prices : pd.DataFrame
        Close prices. Same shape as factor.
    horizons : list[int]
        Forward return horizons in days.
    min_obs : int
        Minimum observations per period.

    Returns
    -------
    dict with keys: horizons (list[int]), ic_values (list[float]).
    """
    ic_values: list[float] = []
    for h in horizons:
        fwd_ret = prices.pct_change(h).shift(-h)
        result = compute_ic(factor, fwd_ret, min_obs=min_obs)
        ic_values.append(float(result["mean"]))

    return {"horizons": horizons, "ic_values": ic_values}


def compute_ts_ic(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    min_obs: int = 30,
) -> dict[str, object]:
    """Compute time-series IC: per-symbol Pearson correlation across time.

    Unlike cross-sectional IC (which correlates across symbols within each date),
    this correlates across dates within each symbol. Measures whether a factor
    predicts an asset's own future returns — the relevant metric for rotation
    and trend-following strategies.

    Parameters
    ----------
    factor : pd.DataFrame
        Factor values. index=date, columns=symbols.
    forward_returns : pd.DataFrame
        Forward returns aligned with factor. Same shape.
    min_obs : int
        Minimum valid observations per symbol. Symbols with fewer are skipped.

    Returns
    -------
    dict with keys: mean (float), per_symbol (dict[str, float]).
    """
    per_symbol: dict[str, float] = {}
    for sym in factor.columns:
        if sym not in forward_returns.columns:
            continue
        f = factor[sym]
        r = forward_returns[sym]
        mask = f.notna() & r.notna()
        if mask.sum() < min_obs:
            continue
        corr, _ = stats.pearsonr(f[mask], r[mask])
        per_symbol[sym] = float(corr)

    if not per_symbol:
        return {"mean": float("nan"), "per_symbol": {}}

    return {
        "mean": float(np.mean(list(per_symbol.values()))),
        "per_symbol": per_symbol,
    }


def compute_turnover(factor: pd.DataFrame) -> float:
    """Compute average factor rank turnover.

    Turnover per period = mean(|rank_change|) / (N - 1), averaged across periods.
    Normalized to [0, 1] range where 0 = no change, 1 = maximum displacement.
    """
    ranks = factor.rank(axis=1)
    n_symbols = factor.shape[1]
    if n_symbols <= 1:
        return 0.0

    turnovers: list[float] = []
    for i in range(1, len(ranks)):
        prev = ranks.iloc[i - 1]
        curr = ranks.iloc[i]
        mask = prev.notna() & curr.notna()
        if mask.sum() < 2:
            continue
        rank_change = (curr[mask] - prev[mask]).abs().mean()
        turnovers.append(float(rank_change / (mask.sum() - 1)))

    if not turnovers:
        return float("nan")
    return float(np.mean(turnovers))
