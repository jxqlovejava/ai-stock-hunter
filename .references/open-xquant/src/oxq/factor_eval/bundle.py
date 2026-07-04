"""FactorBundle — aligned data container for time-series factor evaluation."""

from __future__ import annotations

from dataclasses import dataclass, fields

import pandas as pd


@dataclass(frozen=True)
class AlignmentReport:
    """Summary of data alignment during FactorBundle construction."""

    original_factor_count: int
    aligned_count: int
    loss_ratio: float
    dropped_dates: list[str]
    extra_dates: list[str]
    limit_day_count: int
    limit_day_ratio: float
    suspension_count: int
    suspension_ratio: float

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class FactorBundle:
    """Aligned factor values and price data for evaluation.

    Attributes
    ----------
    factor_values
        Series with MultiIndex (date, asset_code).
    prices
        DataFrame with index=date, columns=asset_code.
    alignment_report
        Summary of alignment process.
    limit_days
        Boolean DataFrame marking limit-up/down days. Same shape as prices.
        Populated by preprocessing.mark_limit_days().
    suspension_days
        Boolean DataFrame marking suspension days. Same shape as prices.
        Populated by preprocessing.mark_suspension_days().
    market_state
        Series with index=date, values in {trend, ranging, crash}.
    asset_meta
        {asset_code: {exchange: str, asset_type: str}}.
    """

    factor_values: pd.Series
    prices: pd.DataFrame
    alignment_report: AlignmentReport
    limit_days: pd.DataFrame | None = None
    suspension_days: pd.DataFrame | None = None
    market_state: pd.Series | None = None
    asset_meta: dict | None = None


def create_bundle(
    factor_values: pd.Series,
    prices: pd.DataFrame,
    forward_periods: list[int],
    market_state: pd.Series | None = None,
    asset_meta: dict | None = None,
) -> FactorBundle:
    """Create a FactorBundle by aligning factor values with price data.

    Parameters
    ----------
    factor_values
        Series with MultiIndex (date, asset_code).
    prices
        DataFrame with index=date, columns=asset_code.
    forward_periods
        List of forward periods (trading days). Used to validate
        that prices extend far enough beyond factor dates.
    market_state
        Optional market regime labels.
    asset_meta
        Optional asset metadata.

    Raises
    ------
    ValueError
        If prices don't extend max(forward_periods) beyond last factor date.
    """
    # Extract unique factor dates
    factor_dates = factor_values.index.get_level_values("date").unique().sort_values()
    price_dates = prices.index.sort_values()

    # Check price coverage: must extend max(forward_periods) beyond last factor date
    max_fwd = max(forward_periods)
    last_factor_date = factor_dates[-1]
    price_dates_after = price_dates[price_dates > last_factor_date]
    if len(price_dates_after) < max_fwd:
        msg = (
            f"Insufficient price coverage: need {max_fwd} trading days after "
            f"last factor date {last_factor_date.date()}, "
            f"but only {len(price_dates_after)} available."
        )
        raise ValueError(msg)

    # Align: keep only factor rows whose date is in price_dates
    aligned_mask = factor_dates.isin(price_dates)
    aligned_dates = factor_dates[aligned_mask]
    dropped_dates = factor_dates[~aligned_mask]

    aligned_factor = factor_values.loc[
        factor_values.index.get_level_values("date").isin(aligned_dates)
    ]

    # Extra dates: in prices but not in factor dates (within factor date range)
    extra_dates = price_dates[
        ~price_dates.isin(factor_dates)
        & (price_dates >= factor_dates[0])
        & (price_dates <= factor_dates[-1])
    ]

    original_count = len(factor_dates)
    aligned_count = len(aligned_dates)

    report = AlignmentReport(
        original_factor_count=original_count,
        aligned_count=aligned_count,
        loss_ratio=(original_count - aligned_count) / original_count
        if original_count > 0
        else 0.0,
        dropped_dates=[str(d.date()) for d in dropped_dates],
        extra_dates=[str(d.date()) for d in extra_dates],
        limit_day_count=0,
        limit_day_ratio=0.0,
        suspension_count=0,
        suspension_ratio=0.0,
    )

    return FactorBundle(
        factor_values=aligned_factor,
        prices=prices,
        alignment_report=report,
        market_state=market_state,
        asset_meta=asset_meta,
    )
