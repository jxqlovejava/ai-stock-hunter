"""Strategy health monitoring — rolling metrics and bad period detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from oxq.portfolio.analytics import RunResult


@dataclass(frozen=True)
class BadPeriod:
    """A detected period of strategy deterioration."""

    start: date
    end: date
    days: int
    avg_sharpe: float


class StrategyMonitor:
    """Monitor strategy health via rolling metrics and bad period detection.

    Consumes a RunResult (the run record) — does not re-fetch data.
    """

    def __init__(
        self,
        result: RunResult,
        benchmark: str | None = None,
        roll_window: int = 63,
        min_bad_days: int = 20,
        gap_days: int = 5,
    ) -> None:
        equity = pd.Series(dict(result.equity_curve))
        daily_ret = equity.pct_change().dropna()

        # Rolling Sharpe (annualized)
        roll_mean = daily_ret.rolling(roll_window).mean()
        roll_std = daily_ret.rolling(roll_window).std()
        self._rolling_sharpe = (roll_mean / roll_std) * np.sqrt(252)

        # Rolling drawdown (from cumulative peak)
        peak = equity.cummax()
        self._rolling_drawdown = (equity - peak) / peak

        # Rolling excess return (annualized)
        if benchmark and benchmark in result.benchmark_prices:
            bench_prices = result.benchmark_prices[benchmark]
            bench_ret = bench_prices.pct_change().dropna()
            common_idx = daily_ret.index.intersection(bench_ret.index)
            excess = daily_ret.reindex(common_idx) - bench_ret.reindex(common_idx)
            self._rolling_excess: pd.Series | None = (
                excess.rolling(roll_window).mean() * 252
            )
        else:
            self._rolling_excess = None

        # Bad period detection
        self._bad_periods = _detect_bad_periods(self._rolling_sharpe, min_bad_days, gap_days)

    @property
    def rolling_sharpe(self) -> pd.Series:
        return self._rolling_sharpe

    @property
    def rolling_drawdown(self) -> pd.Series:
        return self._rolling_drawdown

    @property
    def rolling_excess(self) -> pd.Series | None:
        return self._rolling_excess

    @property
    def bad_periods(self) -> list[BadPeriod]:
        return self._bad_periods

    def summary(self) -> dict:
        current_sharpe = (
            float(self._rolling_sharpe.dropna().iloc[-1])
            if len(self._rolling_sharpe.dropna()) > 0
            else 0.0
        )
        current_dd = (
            float(self._rolling_drawdown.iloc[-1])
            if len(self._rolling_drawdown) > 0
            else 0.0
        )
        current_excess = (
            float(self._rolling_excess.dropna().iloc[-1])
            if self._rolling_excess is not None
            and len(self._rolling_excess.dropna()) > 0
            else None
        )

        if current_sharpe < 0:
            status = "critical"
        elif current_sharpe < 0.5 or current_dd < -0.15:
            status = "warning"
        else:
            status = "healthy"

        return {
            "current_sharpe": current_sharpe,
            "current_drawdown": current_dd,
            "current_excess": current_excess,
            "n_bad_periods": len(self._bad_periods),
            "status": status,
        }


def _detect_bad_periods(
    rolling_sharpe: pd.Series,
    min_bad_days: int,
    gap_days: int = 5,
) -> list[BadPeriod]:
    bad = rolling_sharpe[rolling_sharpe < 0].dropna()
    if len(bad) == 0:
        return []

    periods: list[BadPeriod] = []
    gaps = (bad.index.to_series().diff() > pd.Timedelta(days=gap_days)).cumsum()
    for _, group in bad.groupby(gaps):
        if len(group) >= min_bad_days:
            periods.append(
                BadPeriod(
                    start=group.index[0].date(),
                    end=group.index[-1].date(),
                    days=len(group),
                    avg_sharpe=float(group.mean()),
                ),
            )
    return periods
