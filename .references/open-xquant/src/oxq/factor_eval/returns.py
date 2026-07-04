"""Forward return computation for factor evaluation."""

from __future__ import annotations

import pandas as pd


def compute_forward_returns(
    prices: pd.DataFrame,
    periods: list[int],
    suspension_days: pd.DataFrame | None = None,
) -> dict[int, pd.DataFrame]:
    """Compute holding-period returns for each forward period.

    Parameters
    ----------
    prices
        Close prices. index=date, columns=asset codes.
    periods
        List of forward periods in trading days.
    suspension_days
        Boolean DataFrame (same shape as prices). True = suspended.
        Suspended days are skipped when counting forward periods.

    Returns
    -------
    {period: DataFrame} where each DataFrame has same shape as prices.
    Trailing rows are NaN where future prices are unavailable.
    """
    results: dict[int, pd.DataFrame] = {}
    for n in periods:
        if suspension_days is None:
            # Simple case: future_price / current_price - 1
            fwd = prices.shift(-n) / prices - 1
        else:
            # For each cell, find the n-th non-suspended future trading day
            fwd = _forward_returns_with_suspension(prices, n, suspension_days)
        results[n] = fwd
    return results


def _forward_returns_with_suspension(
    prices: pd.DataFrame,
    period: int,
    suspension_days: pd.DataFrame,
) -> pd.DataFrame:
    """Compute forward returns skipping suspended days per asset."""
    result = pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    for col in prices.columns:
        p = prices[col]
        susp = (
            suspension_days[col]
            if col in suspension_days.columns
            else pd.Series(False, index=prices.index)
        )
        tradeable_indices = p.index[~susp]
        for date in p.index:
            # Find position of current date in tradeable days
            if date not in tradeable_indices:
                continue
            pos_in_tradeable = tradeable_indices.get_loc(date)
            target_pos = pos_in_tradeable + period
            if target_pos >= len(tradeable_indices):
                continue
            target_date = tradeable_indices[target_pos]
            result.loc[date, col] = p[target_date] / p[date] - 1
    return result
