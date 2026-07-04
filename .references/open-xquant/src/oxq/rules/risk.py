"""Risk rules — portfolio-level circuit breakers."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from oxq.core.types import Portfolio, RuleResult


class MaxDrawdownRisk:
    """Portfolio-level circuit breaker based on maximum drawdown.

    Monitors the portfolio's peak-to-trough drawdown. When the drawdown
    exceeds ``max_drawdown``, returns RuleResult with target_positions
    to liquidate and hold=True to freeze trading.

    Parameters
    ----------
    max_drawdown : float
        Maximum allowed drawdown as a decimal fraction.
        Default is 0.15 (15%). Must be between 0 and 1.
    """

    name = "MaxDrawdownRisk"

    def __init__(self, max_drawdown: float = 0.15) -> None:
        self.max_drawdown = max_drawdown
        self._peak_value: Decimal = Decimal("0")

    def evaluate(
        self,
        symbol: str,
        row: pd.Series,
        portfolio: Portfolio,
        prices: dict[str, Decimal] | None = None,
    ) -> RuleResult:
        if prices is None:
            price = Decimal(str(float(row["close"])))
            if not price.is_finite():
                return RuleResult()
            prices = {symbol: price}
        current_value = portfolio.total_value(prices)

        if current_value > self._peak_value:
            self._peak_value = current_value

        if self._peak_value == 0:
            return RuleResult()

        drawdown = (self._peak_value - current_value) / self._peak_value

        if float(drawdown) >= self.max_drawdown:
            if symbol in portfolio.positions:
                return RuleResult(
                    target_positions={symbol: 0.0},
                    hold=True,
                    reason=f"max drawdown {float(drawdown):.1%} >= {self.max_drawdown:.0%}, liquidate {symbol}",
                )
            return RuleResult(
                hold=True,
                reason=f"max drawdown {float(drawdown):.1%} >= {self.max_drawdown:.0%}, freeze trading",
            )

        return RuleResult()


class DailyLossLimitRisk:
    """Freezes trading when single-day loss exceeds a threshold.

    Compares the portfolio value at the start of each trading day
    with the current value. If the intraday loss exceeds
    ``max_daily_loss``, returns RuleResult with hold=True.
    Does NOT liquidate positions — only prevents new orders.

    Parameters
    ----------
    max_daily_loss : float
        Maximum allowed single-day loss as a decimal fraction.
        Default is 0.03 (3%). Must be between 0 and 1.
    """

    name = "DailyLossLimitRisk"

    def __init__(self, max_daily_loss: float = 0.03) -> None:
        self.max_daily_loss = max_daily_loss
        self._day_start_value: Decimal = Decimal("0")
        self._current_date: object = None

    def evaluate(
        self,
        symbol: str,
        row: pd.Series,
        portfolio: Portfolio,
        prices: dict[str, Decimal] | None = None,
    ) -> RuleResult:
        bar_date = row.name if hasattr(row, "name") else None
        if prices is None:
            price = Decimal(str(float(row["close"])))
            if not price.is_finite():
                return RuleResult()
            prices = {symbol: price}
        current_value = portfolio.total_value(prices)

        if bar_date != self._current_date:
            self._current_date = bar_date
            self._day_start_value = current_value

        if self._day_start_value == 0:
            return RuleResult()

        daily_loss = (self._day_start_value - current_value) / self._day_start_value

        if float(daily_loss) >= self.max_daily_loss:
            return RuleResult(
                hold=True,
                reason=f"daily loss {float(daily_loss):.1%} >= {self.max_daily_loss:.0%}, freeze trading",
            )

        return RuleResult()
