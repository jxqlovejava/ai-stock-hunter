"""Walk-forward backtest optimization — rolling train/test windows.

Reduces overfitting by validating strategy parameters out-of-sample
across multiple rolling windows. Reports IS vs OOS performance gap
as a proxy for overfitting severity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardConfig:
    """Walk-forward optimization configuration."""

    train_years: int = 3  # Training window length (years)
    test_months: int = 6  # Out-of-sample test length (months)
    step_months: int = 3  # How far to roll forward each step
    min_train_samples: int = 200  # Minimum number of bars in training set
    min_test_samples: int = 30  # Minimum number of bars in test set


@dataclass
class WalkForwardWindow:
    """Single walk-forward window result."""

    window_index: int = 0
    train_start: str = ""
    train_end: str = ""
    test_start: str = ""
    test_end: str = ""
    best_params: dict[str, Any] = field(default_factory=dict)
    train_annual_return: float = 0.0
    train_sharpe: float = 0.0
    train_max_dd: float = 0.0
    test_annual_return: float = 0.0
    test_sharpe: float = 0.0
    test_max_dd: float = 0.0
    is_oos_return_gap: float = 0.0  # IS annual return - OOS annual return


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward optimization result."""

    windows: list[WalkForwardWindow] = field(default_factory=list)
    oos_annual_returns: list[float] = field(default_factory=list)
    oos_sharpe_ratios: list[float] = field(default_factory=list)
    avg_oos_annual_return: float = 0.0
    avg_oos_sharpe: float = 0.0
    max_oos_drawdown: float = 0.0
    win_rate: float = 0.0  # % of windows with positive OOS return
    avg_is_oos_return_gap: float = 0.0  # Average IS-OOS gap (proxy for overfitting)
    avg_is_oos_sharpe_drop: float = 0.0  # Average Sharpe drop from IS to OOS

    def is_overfit(self) -> bool:
        """Heuristic: severe IS→OOS drop suggests overfitting."""
        return self.avg_is_oos_return_gap > 15.0 or self.avg_is_oos_sharpe_drop > 0.5


class WalkForwardOptimizer:
    """Rolling walk-forward validation for strategy parameters.

    Usage:
        wfo = WalkForwardOptimizer(data, param_grid)
        result = wfo.run(evaluate_strategy_fn)
    """

    def __init__(self, all_data: pd.DataFrame):
        """
        Args:
            all_data: DataFrame with datetime index and price/factor columns.
        """
        self._data = all_data.sort_index()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        evaluate_fn,
        param_grid: dict[str, list[Any]],
        config: Optional[WalkForwardConfig] = None,
    ) -> WalkForwardResult:
        """Run walk-forward optimization.

        Args:
            evaluate_fn: Function(params, train_data, test_data) -> dict
                Returns dict with keys: annual_return, sharpe, max_dd.
            param_grid: Parameter grid for grid search.
            config: Walk-forward configuration.

        Returns:
            WalkForwardResult with all window results.
        """
        cfg = config or WalkForwardConfig()
        result = WalkForwardResult()

        windows = self._generate_windows(cfg)
        logger.info("Walk-forward: %d windows", len(windows))

        for i, (train_data, test_data, train_start, train_end,
                test_start, test_end) in enumerate(windows):
            if len(train_data) < cfg.min_train_samples:
                logger.debug("Window %d: insufficient train samples (%d), skip",
                             i, len(train_data))
                continue
            if len(test_data) < cfg.min_test_samples:
                logger.debug("Window %d: insufficient test samples (%d), skip",
                             i, len(test_data))
                continue

            # Grid search over params on training data
            best_params, best_train_score = self._grid_search(
                evaluate_fn, param_grid, train_data, test_data=None
            )

            # Evaluate best params on OOS test data
            test_metrics = evaluate_fn(best_params, None, test_data)
            train_metrics = evaluate_fn(best_params, train_data, None)

            window = WalkForwardWindow(
                window_index=i,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                best_params=best_params,
                train_annual_return=train_metrics.get("annual_return", 0.0),
                train_sharpe=train_metrics.get("sharpe", 0.0),
                train_max_dd=train_metrics.get("max_dd", 0.0),
                test_annual_return=test_metrics.get("annual_return", 0.0),
                test_sharpe=test_metrics.get("sharpe", 0.0),
                test_max_dd=test_metrics.get("max_dd", 0.0),
                is_oos_return_gap=(
                    train_metrics.get("annual_return", 0.0)
                    - test_metrics.get("annual_return", 0.0)
                ),
            )

            result.windows.append(window)
            result.oos_annual_returns.append(window.test_annual_return)
            result.oos_sharpe_ratios.append(window.test_sharpe)

            logger.info(
                "Window %d: IS ret %.1f%% / OOS ret %.1f%% (gap %.1f%%)",
                i,
                window.train_annual_return * 100,
                window.test_annual_return * 100,
                window.is_oos_return_gap * 100,
            )

        # Aggregate
        if result.oos_annual_returns:
            result.avg_oos_annual_return = sum(result.oos_annual_returns) / len(result.oos_annual_returns)
            result.avg_oos_sharpe = sum(result.oos_sharpe_ratios) / len(result.oos_sharpe_ratios)
            result.win_rate = sum(1 for r in result.oos_annual_returns if r > 0) / len(result.oos_annual_returns)

        if result.windows:
            result.max_oos_drawdown = min(w.test_max_dd for w in result.windows)
            result.avg_is_oos_return_gap = sum(w.is_oos_return_gap for w in result.windows) / len(result.windows)
            result.avg_is_oos_sharpe_drop = sum(
                w.train_sharpe - w.test_sharpe for w in result.windows
            ) / len(result.windows)

        return result

    # ------------------------------------------------------------------
    # Window generation
    # ------------------------------------------------------------------

    def _generate_windows(self, cfg: WalkForwardConfig) -> list[tuple]:
        """Generate (train_data, test_data, train_start, train_end, test_start, test_end) tuples."""
        windows = []
        dates = sorted(self._data.index.unique())

        if not dates:
            return windows

        start_date = dates[0]
        end_date = dates[-1]

        train_delta = timedelta(days=cfg.train_years * 365)
        test_delta = timedelta(days=cfg.test_months * 30)
        step_delta = timedelta(days=cfg.step_months * 30)

        current = start_date + train_delta

        while current + test_delta <= end_date:
            train_start = current - train_delta
            train_end = current
            test_start = current
            test_end = current + test_delta

            train_mask = (self._data.index >= train_start) & (self._data.index < train_end)
            test_mask = (self._data.index >= test_start) & (self._data.index < test_end)

            train_data = self._data[train_mask]
            test_data = self._data[test_mask]

            ts = train_start.strftime("%Y-%m-%d") if hasattr(train_start, "strftime") else str(train_start)[:10]
            te = train_end.strftime("%Y-%m-%d") if hasattr(train_end, "strftime") else str(train_end)[:10]
            tss = test_start.strftime("%Y-%m-%d") if hasattr(test_start, "strftime") else str(test_start)[:10]
            tse = test_end.strftime("%Y-%m-%d") if hasattr(test_end, "strftime") else str(test_end)[:10]

            windows.append((train_data, test_data, ts, te, tss, tse))
            current += step_delta

        return windows

    def _grid_search(
        self,
        evaluate_fn,
        param_grid: dict[str, list[Any]],
        train_data: pd.DataFrame,
        test_data: Optional[pd.DataFrame] = None,
    ) -> tuple[dict[str, Any], dict[str, float]]:
        """Simple grid search over parameter combinations.

        Returns (best_params, best_metrics).
        """
        best_params = {}
        best_score = float("-inf")

        # Generate all combinations
        from itertools import product

        keys = list(param_grid.keys())
        values_list = list(param_grid.values())
        combinations = list(product(*values_list))

        for combo in combinations:
            params = dict(zip(keys, combo))
            metrics = evaluate_fn(params, train_data, test_data)
            # Default objective: maximize Sharpe ratio
            score = metrics.get("sharpe", 0.0)

            if score > best_score:
                best_score = score
                best_params = params

        # Re-evaluate with best params to get full metrics
        best_metrics = evaluate_fn(best_params, train_data, test_data)
        return best_params, best_metrics
