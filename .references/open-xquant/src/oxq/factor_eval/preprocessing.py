"""Preprocessing functions for A-share and other market-specific rules."""

from __future__ import annotations

import pandas as pd

from oxq.factor_eval.bundle import FactorBundle


def apply_t1_offset(bundle: FactorBundle) -> FactorBundle:
    """Shift factor values forward by 1 trading day.

    T-day factor value maps to T+1 day's holding period.
    The last factor value is dropped (no next trading day).
    Returns a new FactorBundle; does not mutate the original.
    """
    fv = bundle.factor_values
    dates = fv.index.get_level_values("date")
    assets = fv.index.get_level_values("asset")

    price_dates = bundle.prices.index.sort_values()
    new_indices = []
    new_values = []

    for date, asset, value in zip(dates, assets, fv.values):
        pos = price_dates.get_loc(date) if date in price_dates else None
        if pos is None or pos + 1 >= len(price_dates):
            continue
        next_date = price_dates[pos + 1]
        new_indices.append((next_date, asset))
        new_values.append(value)

    if not new_indices:
        new_factor = pd.Series(
            dtype=float,
            index=pd.MultiIndex.from_tuples([], names=["date", "asset"]),
        )
    else:
        mi = pd.MultiIndex.from_tuples(new_indices, names=["date", "asset"])
        new_factor = pd.Series(new_values, index=mi, dtype=float)

    return FactorBundle(
        factor_values=new_factor,
        prices=bundle.prices,
        alignment_report=bundle.alignment_report,
        limit_days=bundle.limit_days,
        suspension_days=bundle.suspension_days,
        market_state=bundle.market_state,
        asset_meta=bundle.asset_meta,
    )


def _limit_threshold(code: str, asset_meta: dict | None) -> float | None:
    """Return the limit threshold for an asset, or None if no limit applies."""
    if asset_meta is None or code not in asset_meta:
        return None
    meta = asset_meta[code]
    exchange = meta.get("exchange", "")
    if exchange not in ("SH", "SZ"):
        return None
    # ChiNext (30x) and STAR Market (68x) use 20%
    if code.startswith("30") or code.startswith("68"):
        return 0.20
    return 0.10


def mark_limit_days(
    prices: pd.DataFrame,
    asset_meta: dict | None = None,
) -> pd.DataFrame:
    """Mark limit-up/down days based on daily return thresholds.

    Returns a boolean DataFrame with same shape as prices.
    """
    pct = prices.pct_change()
    result = pd.DataFrame(False, index=prices.index, columns=prices.columns)

    for col in prices.columns:
        threshold = _limit_threshold(col, asset_meta)
        if threshold is None:
            continue
        result[col] = pct[col].abs() >= threshold - 1e-9  # tolerance for float

    return result


def mark_suspension_days(
    prices: pd.DataFrame,
    volume: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Mark suspension days: zero return or zero volume.

    Returns a boolean DataFrame with same shape as prices.
    """
    # Zero daily return (price unchanged)
    pct = prices.pct_change()
    zero_return = pct.abs() < 1e-12
    # First row has NaN pct_change -- not a suspension
    zero_return.iloc[0] = False

    result = zero_return.copy()

    if volume is not None:
        zero_vol = volume == 0
        result = result | zero_vol

    return result
