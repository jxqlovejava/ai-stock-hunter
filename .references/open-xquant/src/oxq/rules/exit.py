"""Exit rule — signals intent to close position when fast MA drops below slow MA."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from oxq.core.types import Portfolio, RuleResult


class ExitRule:
    """Signal intent to close position when the fast indicator drops below the slow one."""

    name = "ExitRule"

    def __init__(self, fast: str, slow: str) -> None:
        self.fast = fast
        self.slow = slow

    def evaluate(
        self,
        symbol: str,
        row: pd.Series,
        portfolio: Portfolio,
        prices: dict[str, Decimal] | None = None,
    ) -> RuleResult:
        if symbol in portfolio.positions and row[self.fast] < row[self.slow]:
            return RuleResult(
                target_positions={symbol: 0.0},
                reason=f"{self.fast} < {self.slow}, exit {symbol}",
            )
        return RuleResult()
