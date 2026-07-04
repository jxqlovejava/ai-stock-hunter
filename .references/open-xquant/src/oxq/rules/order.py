"""Order rules — signal intent to exit positions for stop-loss, take-profit, trailing stop."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from oxq.core.types import Portfolio, RuleResult


class StopLossRule:
    """Signal intent to exit when unrealized loss exceeds a threshold.

    Returns RuleResult with target_positions={symbol: 0.0} when the current
    price drops to or below avg_cost * (1 - threshold).

    Parameters
    ----------
    threshold : float
        Maximum allowed loss as a decimal fraction of entry cost.
        Default is 0.05 (5%). Must be between 0 and 1.
    """

    name = "StopLossRule"

    def __init__(self, threshold: float = 0.05) -> None:
        self.threshold = threshold

    def evaluate(
        self,
        symbol: str,
        row: pd.Series,
        portfolio: Portfolio,
        prices: dict[str, Decimal] | None = None,
    ) -> RuleResult:
        if symbol not in portfolio.positions:
            return RuleResult()
        pos = portfolio.positions[symbol]
        price = Decimal(str(float(row["close"])))
        stop_price = pos.avg_cost * (1 - Decimal(str(self.threshold)))
        if price <= stop_price:
            return RuleResult(
                target_positions={symbol: 0.0},
                reason=f"stop loss triggered for {symbol}: price {price} <= {stop_price}",
            )
        return RuleResult()


class TakeProfitRule:
    """Signal intent to exit when unrealized profit exceeds a threshold.

    Returns RuleResult with target_positions={symbol: 0.0} when the current
    price rises to or above avg_cost * (1 + threshold).

    Parameters
    ----------
    threshold : float
        Profit target as a decimal fraction of entry cost.
        Default is 0.15 (15%). Must be between 0 and 1.
    """

    name = "TakeProfitRule"

    def __init__(self, threshold: float = 0.15) -> None:
        self.threshold = threshold

    def evaluate(
        self,
        symbol: str,
        row: pd.Series,
        portfolio: Portfolio,
        prices: dict[str, Decimal] | None = None,
    ) -> RuleResult:
        if symbol not in portfolio.positions:
            return RuleResult()
        pos = portfolio.positions[symbol]
        price = Decimal(str(float(row["close"])))
        target_price = pos.avg_cost * (1 + Decimal(str(self.threshold)))
        if price >= target_price:
            return RuleResult(
                target_positions={symbol: 0.0},
                reason=f"take profit triggered for {symbol}: price {price} >= {target_price}",
            )
        return RuleResult()


class TrailingStopRule:
    """Signal intent to exit when price retraces from high-water mark.

    Tracks the high-water mark per symbol internally. Returns RuleResult
    with target_positions={symbol: 0.0} when close <= hwm * (1 - trail_pct).

    Parameters
    ----------
    trail_pct : float
        Maximum allowed retracement from high-water mark as a
        decimal fraction. Default is 0.05 (5%). Must be between 0 and 1.
    """

    name = "TrailingStopRule"

    def __init__(self, trail_pct: float = 0.05) -> None:
        self.trail_pct = trail_pct
        self._high_water_marks: dict[str, Decimal] = {}

    def evaluate(
        self,
        symbol: str,
        row: pd.Series,
        portfolio: Portfolio,
        prices: dict[str, Decimal] | None = None,
    ) -> RuleResult:
        if symbol not in portfolio.positions:
            return RuleResult()

        close = Decimal(str(float(row["close"])))

        # Update high-water mark
        hwm = self._high_water_marks.get(symbol, Decimal("0"))
        if close > hwm:
            hwm = close
            self._high_water_marks[symbol] = hwm

        stop_level = hwm * (1 - Decimal(str(self.trail_pct)))
        if close <= stop_level:
            return RuleResult(
                target_positions={symbol: 0.0},
                reason=f"trailing stop triggered for {symbol}: close {close} <= {stop_level}",
            )
        return RuleResult()
