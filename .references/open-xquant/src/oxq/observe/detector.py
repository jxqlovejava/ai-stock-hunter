"""Market state detection — volatility-based regime classification."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from oxq.portfolio.analytics import RunResult


class MarketStateDetector:
    """Classify market state (high/normal/low volatility) from RunResult.

    Consumes result.mktdata — does not re-fetch data.
    """

    def __init__(
        self,
        result: RunResult,
        symbols: tuple[str, ...] | None = None,
        vol_lookback: int = 20,
        high_vol_multiplier: float = 1.3,
        low_vol_multiplier: float = 0.7,
    ) -> None:
        syms = symbols or tuple(result.mktdata.keys())

        asset_vols = pd.DataFrame({
            sym: result.mktdata[sym]["close"].pct_change().rolling(vol_lookback).std()
            * np.sqrt(252)
            for sym in syms
        })
        self._market_vol = asset_vols.mean(axis=1)

        self._vol_median = float(self._market_vol.median())
        self._high_vol_line = self._vol_median * high_vol_multiplier
        self._low_vol_line = self._vol_median * low_vol_multiplier

        self._states = pd.Series(index=self._market_vol.index, dtype=object)
        valid = self._market_vol.dropna()
        self._states.loc[valid.index] = "normal"
        self._states.loc[valid[valid > self._high_vol_line].index] = "high"
        self._states.loc[valid[valid < self._low_vol_line].index] = "low"

        self._high_vol_mask = self._states == "high"
        self._low_vol_mask = self._states == "low"

    @property
    def market_vol(self) -> pd.Series:
        return self._market_vol

    @property
    def states(self) -> pd.Series:
        return self._states

    @property
    def high_vol_mask(self) -> pd.Series:
        return self._high_vol_mask

    @property
    def low_vol_mask(self) -> pd.Series:
        return self._low_vol_mask

    @property
    def vol_median(self) -> float:
        return self._vol_median

    @property
    def high_vol_line(self) -> float:
        return self._high_vol_line

    @property
    def low_vol_line(self) -> float:
        return self._low_vol_line

    def performance_by_state(self, result: RunResult) -> dict[str, dict]:
        """Break down strategy performance by market state."""
        daily_ret = pd.Series(dict(result.equity_curve)).pct_change().dropna()
        valid_states = self._states.dropna()
        common_idx = daily_ret.index.intersection(valid_states.index)

        if len(common_idx) < len(daily_ret) * 0.5:
            warnings.warn(
                f"Only {len(common_idx)}/{len(daily_ret)} dates overlap between "
                f"result and detector states. Results may be unreliable.",
                stacklevel=2,
            )

        perf: dict[str, dict] = {}
        for state in ("high", "normal", "low"):
            mask = valid_states.reindex(common_idx) == state
            state_returns = daily_ret.reindex(common_idx)[mask]
            if len(state_returns) == 0:
                continue
            days = len(state_returns)
            ann_ret = float(state_returns.mean() * 252)
            std = float(state_returns.std())
            sharpe = float(ann_ret / (std * np.sqrt(252))) if std > 0 else 0.0
            perf[state] = {
                "days": days,
                "ann_return": ann_ret,
                "sharpe": sharpe,
            }
        return perf
