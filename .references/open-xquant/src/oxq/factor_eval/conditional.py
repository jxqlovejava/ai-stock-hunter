"""Market state conditional analysis for factor evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd

_MIN_STATE_SAMPLE = 30


def compute_conditional_analysis(
    factor_values: pd.Series,
    forward_returns: pd.DataFrame,
    market_state: pd.Series | None = None,
    signal_threshold: float = 0.0,
    min_sample_warn: int = _MIN_STATE_SAMPLE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Compute factor metrics grouped by market state.

    Returns dict with by_state (dict of state -> metrics), skipped (bool).
    """
    if market_state is None:
        return {"by_state": {}, "skipped": True}

    dates = factor_values.index.get_level_values("date")
    assets = factor_values.index.get_level_values("asset")

    records = []
    for date, asset, fval in zip(dates, assets, factor_values.values):
        if start_date and str(date.date()) < start_date:
            continue
        if end_date and str(date.date()) > end_date:
            continue
        if asset not in forward_returns.columns or date not in forward_returns.index:
            continue
        if date not in market_state.index:
            continue
        ret = forward_returns.loc[date, asset]
        if np.isnan(fval) or np.isnan(ret):
            continue
        records.append({
            "date": date, "asset": asset, "factor": fval,
            "return": ret, "state": market_state[date],
        })

    if not records:
        return {"by_state": {}, "skipped": False}

    df = pd.DataFrame(records)
    states = df["state"].unique()
    by_state = {}

    for state in sorted(states):
        state_df = df[df["state"] == state]
        n = len(state_df)

        factors_arr = state_df["factor"].values
        returns_arr = state_df["return"].values

        long_mask = factors_arr > signal_threshold
        short_mask = factors_arr < signal_threshold
        long_hits = np.sum(long_mask & (returns_arr > 0))
        short_hits = np.sum(short_mask & (returns_arr < 0))
        signal_count = int(np.sum(long_mask) + np.sum(short_mask))
        hit_rate = float((long_hits + short_hits) / signal_count) if signal_count > 0 else float("nan")

        long_returns = returns_arr[long_mask]
        wins = long_returns[long_returns > 0]
        losses = long_returns[long_returns < 0]
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.0
        if avg_loss == 0.0:
            pl_ratio = float("inf") if avg_win > 0 else float("nan")
        else:
            pl_ratio = avg_win / avg_loss

        avg_return = float(np.mean(returns_arr))

        warning = None
        if n < min_sample_warn:
            warning = f"Sample size {n} < {min_sample_warn}, results for reference only."

        by_state[state] = {
            "hit_rate": hit_rate,
            "profit_loss_ratio": pl_ratio,
            "avg_return": avg_return,
            "sample_count": n,
            "warning": warning,
        }

    return {"by_state": by_state, "skipped": False}
