"""Multi-asset comparison for factor evaluation."""

from __future__ import annotations

from oxq.factor_eval.bundle import FactorBundle
from oxq.factor_eval.decay_curve import compute_decay_curve
from oxq.factor_eval.hit_rate import compute_hit_rate
from oxq.factor_eval.profit_loss import compute_profit_loss_ratio
from oxq.factor_eval.returns import compute_forward_returns


def compute_asset_comparison(
    bundle: FactorBundle,
    forward_periods: list[int],
    signal_threshold: float = 0.0,
    method: str = "spearman",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Compare factor performance across assets in a multi-asset FactorBundle.

    Groups factor_values by asset, runs per-asset evaluation.
    Single-asset bundles return skipped=True.

    Returns dict with by_asset (dict of asset -> metrics), skipped (bool).
    """
    assets = bundle.factor_values.index.get_level_values("asset").unique()

    if len(assets) < 2:
        return {"by_asset": {}, "skipped": True}

    fwd_returns = compute_forward_returns(
        bundle.prices, forward_periods,
        suspension_days=bundle.suspension_days,
    )

    by_asset: dict = {}
    for asset in sorted(assets):
        asset_fv = bundle.factor_values.loc[
            bundle.factor_values.index.get_level_values("asset") == asset
        ]

        primary_fwd = fwd_returns[forward_periods[0]]
        hr = compute_hit_rate(
            asset_fv, primary_fwd,
            signal_threshold=signal_threshold,
            start_date=start_date, end_date=end_date,
        )

        pl = compute_profit_loss_ratio(
            asset_fv, primary_fwd,
            signal_threshold=signal_threshold,
            start_date=start_date, end_date=end_date,
        )

        decay = compute_decay_curve(
            asset_fv, fwd_returns,
            periods=forward_periods,
            method=method,
            start_date=start_date, end_date=end_date,
        )

        by_asset[asset] = {
            "hit_rate": hr["long_hit_rate"],
            "profit_loss_ratio": pl["ratio"],
            "decay_half_life": decay["half_life"],
            "sample_count": hr["sample_count"],
            "rolling_hit_rate": hr["rolling_hit_rate"],
            "decay_correlations": decay["correlations"],
        }

    return {"by_asset": by_asset, "skipped": False}
