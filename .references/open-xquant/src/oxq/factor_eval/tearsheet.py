"""Tear sheet -- orchestrate factor evaluation and generate visual report."""

from __future__ import annotations

import os
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from oxq.factor_eval.bias import detect_lookahead_bias
from oxq.factor_eval.bundle import FactorBundle
from oxq.factor_eval.cash_period import compute_cash_period_value
from oxq.factor_eval.comparison import compute_asset_comparison
from oxq.factor_eval.conditional import compute_conditional_analysis
from oxq.factor_eval.decay_curve import compute_decay_curve
from oxq.factor_eval.hit_rate import compute_hit_rate
from oxq.factor_eval.profit_loss import compute_profit_loss_ratio
from oxq.factor_eval.returns import compute_forward_returns


def generate_tearsheet(
    bundle: FactorBundle,
    forward_periods: list[int] | None = None,
    signal_threshold: float = 0.0,
    exclude_limit_days: bool = False,
    rolling_window: int = 60,
    method: str = "spearman",
    output_dir: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Generate a complete factor evaluation tear sheet.

    Orchestrates forward return computation, bias detection, hit rate,
    and decay curve analysis. Produces summary dict + PNG charts.

    Parameters
    ----------
    bundle
        FactorBundle with aligned data.
    forward_periods
        Periods for decay curve. Default [1, 3, 5, 10, 20, 40, 60].
    signal_threshold
        Threshold for hit rate signals.
    exclude_limit_days
        Whether to exclude limit days from hit rate.
    rolling_window
        Window for rolling hit rate.
    method
        Correlation method for decay curve.
    output_dir
        Directory for PNG files. Default: temp directory.
    start_date, end_date
        Optional date range for analysis.

    Returns
    -------
    dict with 'summary' (structured metrics) and 'charts' (PNG paths).
    """
    if forward_periods is None:
        forward_periods = [1, 3, 5, 10, 20, 40, 60]

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="oxq_tearsheet_")

    # 1. Compute forward returns
    fwd_returns = compute_forward_returns(
        bundle.prices,
        forward_periods,
        suspension_days=bundle.suspension_days,
    )

    # 2. Lookahead bias detection
    bias_result = detect_lookahead_bias(
        bundle.factor_values,
        bundle.prices,
    )

    # 3. Hit rate (using first forward period)
    primary_period = forward_periods[0]
    hr_result = compute_hit_rate(
        bundle.factor_values,
        fwd_returns[primary_period],
        signal_threshold=signal_threshold,
        exclude_limit_days=exclude_limit_days,
        limit_days=bundle.limit_days,
        rolling_window=rolling_window,
        start_date=start_date,
        end_date=end_date,
    )

    # 4. Decay curve
    decay_result = compute_decay_curve(
        bundle.factor_values,
        fwd_returns,
        periods=forward_periods,
        method=method,
        start_date=start_date,
        end_date=end_date,
    )

    # 5. P1: Profit/loss ratio
    pl_result = compute_profit_loss_ratio(
        bundle.factor_values,
        fwd_returns[primary_period],
        signal_threshold=signal_threshold,
        start_date=start_date,
        end_date=end_date,
    )

    # 6. P1: Cash period value
    cp_result = compute_cash_period_value(
        bundle.factor_values,
        fwd_returns[primary_period],
        signal_threshold=signal_threshold,
        start_date=start_date,
        end_date=end_date,
    )

    # 7. P1: Conditional analysis (auto-skip if no market_state)
    cond_result = compute_conditional_analysis(
        bundle.factor_values,
        fwd_returns[primary_period],
        market_state=bundle.market_state,
        signal_threshold=signal_threshold,
        start_date=start_date,
        end_date=end_date,
    )

    # 8. P1: Multi-asset comparison (auto-skip if single asset)
    comp_result = compute_asset_comparison(
        bundle,
        forward_periods=forward_periods,
        signal_threshold=signal_threshold,
        method=method,
        start_date=start_date,
        end_date=end_date,
    )

    # 9. Generate charts
    rolling_hr_path = _plot_rolling_hit_rate(
        hr_result["rolling_hit_rate"],
        output_dir,
    )
    decay_path = _plot_decay_curve(decay_result, output_dir)
    pl_dist_path = _plot_return_distribution(
        pl_result["return_distribution"], output_dir,
    )
    cp_path = _plot_cash_period(cp_result, output_dir)

    # Build hit_rate summary (keep rolling Series for programmatic access)
    hr_summary = {**hr_result}

    return {
        "summary": {
            "alignment_report": bundle.alignment_report.to_dict(),
            "lookahead_bias": bias_result,
            "hit_rate": hr_summary,
            "decay_curve": decay_result,
            "profit_loss": pl_result,
            "cash_period": cp_result,
            "conditional": cond_result,
            "comparison": comp_result,
        },
        "charts": {
            "rolling_hit_rate": rolling_hr_path,
            "decay_curve": decay_path,
            "profit_loss_distribution": pl_dist_path,
            "cash_period": cp_path,
        },
    }


def _plot_rolling_hit_rate(rolling: pd.Series, output_dir: str) -> str:
    """Plot rolling hit rate with 50% baseline."""
    fig, ax = plt.subplots(figsize=(12, 5))
    if not rolling.empty:
        ax.plot(rolling.index, rolling.values, label="Rolling Hit Rate", linewidth=1.5)
    ax.axhline(y=0.5, color="gray", linestyle="--", label="50% Baseline")
    ax.set_ylabel("Hit Rate")
    ax.set_xlabel("Date")
    ax.set_title("Rolling Hit Rate")
    ax.legend()
    ax.grid(True, alpha=0.3)
    path = os.path.join(output_dir, "rolling_hit_rate.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_decay_curve(decay_result: dict, output_dir: str) -> str:
    """Plot factor decay curve with half-life and inflection markers."""
    fig, ax = plt.subplots(figsize=(10, 5))
    corrs = decay_result["correlations"]
    periods = sorted(corrs.keys())
    values = [corrs[p] for p in periods]

    ax.plot(periods, values, marker="o", linewidth=2, label="Correlation")

    if decay_result["half_life"] is not None:
        ax.axvline(
            x=decay_result["half_life"],
            color="orange",
            linestyle="--",
            label=f"Half-life ({decay_result['half_life']}d)",
        )
    if decay_result["inflection_point"] is not None:
        ax.axvline(
            x=decay_result["inflection_point"],
            color="red",
            linestyle=":",
            label=f"Inflection ({decay_result['inflection_point']}d)",
        )

    ax.axhline(y=0, color="gray", linestyle="-", alpha=0.3)
    ax.set_xlabel("Forward Period (days)")
    ax.set_ylabel("Correlation")
    ax.set_title("Factor Decay Curve")
    ax.legend()
    ax.grid(True, alpha=0.3)
    path = os.path.join(output_dir, "decay_curve.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_return_distribution(returns: list[float], output_dir: str) -> str:
    """Plot histogram of holding-period returns."""
    fig, ax = plt.subplots(figsize=(10, 5))
    if returns:
        ax.hist(returns, bins=30, edgecolor="black", alpha=0.7)
        ax.axvline(x=0, color="red", linestyle="--", alpha=0.5)
    ax.set_xlabel("Return")
    ax.set_ylabel("Frequency")
    ax.set_title("Holding Period Return Distribution")
    ax.grid(True, alpha=0.3)
    path = os.path.join(output_dir, "profit_loss_distribution.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_cash_period(cp_result: dict, output_dir: str) -> str:
    """Plot holding vs cash period average returns."""
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = ["Holding", "Cash"]
    values = [
        cp_result.get("holding_avg_return", 0) or 0,
        cp_result.get("cash_avg_return", 0) or 0,
    ]
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in values]
    ax.bar(labels, values, color=colors, edgecolor="black", alpha=0.8)
    ax.axhline(y=0, color="gray", linestyle="-", alpha=0.3)
    ax.set_ylabel("Average Return")
    ax.set_title("Holding vs Cash Period Returns")
    ax.grid(True, alpha=0.3, axis="y")
    path = os.path.join(output_dir, "cash_period.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path
