# -*- coding: utf-8 -*-
"""Position adding (pyramiding) engine — pyramid / equal / signal-based."""

from __future__ import annotations

import logging

from .types import AddCheckResult

logger = logging.getLogger(__name__)

_MIN_ADD_FRACTION = 0.01  # 1 % minimum to avoid tiny meaningless adds


class AddRuleEngine:
    """Position adding rules engine — determines if/when to pyramid."""

    def __init__(
        self,
        max_position_pct: float = 20.0,
        min_pnl_for_add: float = -0.05,
        min_add_interval_days: int = 5,
        max_adds: int = 3,
        base_weight: float = 10.0,
        signal_threshold: float = 0.6,
    ) -> None:
        self.max_position_pct = max_position_pct
        self.min_pnl_for_add = min_pnl_for_add
        self.min_add_interval_days = min_add_interval_days
        self.max_adds = max_adds
        self.base_weight = base_weight
        self.signal_threshold = signal_threshold

    def check(
        self,
        position: dict,
        new_signal_strength: float = 0.0,
        days_since_last_add: float | None = None,
    ) -> AddCheckResult:
        """Evaluate whether a position qualifies for an add.

        Parameters
        ----------
        position :
            Dict with keys: ``symbol``, ``pnl_pct``, ``current_weight_pct``,
            ``add_count``, ``last_add_price``.
        new_signal_strength :
            Signal strength (0.0 -- 1.0) for signal-based method.
        days_since_last_add :
            Days since last add. ``None`` skips the interval gate.

        Returns
        -------
        AddCheckResult
        """
        symbol = position.get("symbol", "")
        pnl_pct = position.get("pnl_pct", 0.0)
        current_weight_pct = position.get("current_weight_pct", 0.0)
        add_count = position.get("add_count", 0)
        current_price = position.get("current_price", 0.0)
        last_add_price = position.get("last_add_price", None)

        # ---- Determine additive method -----------------------------------

        if new_signal_strength > self.signal_threshold:
            method = "signal"
        elif pnl_pct > 0 and add_count == 0:
            method = "equal"
        else:
            method = "pyramid"

        # ---- Safety gates ------------------------------------------------

        # 1) Max adds reached
        if add_count >= self.max_adds:
            logger.info("%s: max adds (%d) reached", symbol, self.max_adds)
            return self._reject(symbol, f"Max adds ({self.max_adds}) reached", method)

        # 2) PnL too negative (do not add to losers)
        if pnl_pct < self.min_pnl_for_add:
            logger.info(
                "%s: PnL %.1f%% below min %.1f%%",
                symbol, pnl_pct * 100, self.min_pnl_for_add * 100,
            )
            return self._reject(
                symbol,
                f"PnL {pnl_pct * 100:.1f}% below min {self.min_pnl_for_add * 100:.1f}%",
                method,
            )

        # 3) Position would exceed max portfolio weight
        add_fraction = self._calc_add_fraction(method, add_count, new_signal_strength)
        projected_weight = current_weight_pct + add_fraction * self.base_weight
        if projected_weight > self.max_position_pct:
            logger.info(
                "%s: projected weight %.1f%% exceeds max %.1f%%",
                symbol, projected_weight, self.max_position_pct,
            )
            return self._reject(
                symbol,
                f"Projected weight {projected_weight:.1f}% exceeds {self.max_position_pct:.1f}%",
                method,
            )

        # 4) Add interval too short
        if (
            days_since_last_add is not None
            and days_since_last_add < self.min_add_interval_days
        ):
            logger.info(
                "%s: %.1f d since last add (min %d)",
                symbol, days_since_last_add, self.min_add_interval_days,
            )
            return self._reject(
                symbol,
                f"Only {days_since_last_add:.1f} d since last add "
                f"(min {self.min_add_interval_days} d)",
                method,
            )

        # 5) Pyramid requires price above last add price
        if method == "pyramid" and last_add_price is not None and current_price < last_add_price:
            logger.info(
                "%s: price %.2f < last add %.2f — pyramid needs price above",
                symbol, current_price, last_add_price,
            )
            return self._reject(
                symbol,
                f"Price {current_price:.2f} below last add {last_add_price:.2f}",
                method,
            )

        # 6) Equal method requires positive PnL
        if method == "equal" and pnl_pct <= 0:
            return self._reject(
                symbol,
                f"Equal add requires positive PnL (got {pnl_pct * 100:.1f}%)",
                method,
            )

        # ---- Validate fraction -------------------------------------------

        if add_fraction < _MIN_ADD_FRACTION:
            logger.info(
                "%s: fraction %.4f below min %.4f",
                symbol, add_fraction, _MIN_ADD_FRACTION,
            )
            return self._reject(
                symbol,
                f"Add fraction {add_fraction:.4f} below minimum",
                method,
            )

        logger.info(
            "%s: ADD via %s (fraction=%.3f, add#=%d)",
            symbol, method, add_fraction, add_count + 1,
        )

        return AddCheckResult(
            symbol=symbol,
            should_add=True,
            reason=f"Add #{add_count + 1} via {method} ({add_fraction:.1%})",
            add_method=method,
            add_fraction=add_fraction,
        )

    # ---- internal helpers -----------------------------------------------

    @staticmethod
    def _reject(symbol: str, reason: str, method: str) -> AddCheckResult:
        return AddCheckResult(
            symbol=symbol,
            should_add=False,
            reason=reason,
            add_method=method,
            add_fraction=0.0,
        )

    @staticmethod
    def _calc_add_fraction(method: str, add_count: int, signal_strength: float) -> float:
        """Return the fraction of the original position to add."""
        if method == "pyramid":
            return 0.5 ** (add_count + 1)  # 0.5 → 0.25 → 0.125
        if method == "signal":
            return max(0.0, min(1.0, signal_strength))
        if method == "equal":
            return 1.0
        # fallback — treat as pyramid
        return 0.5 ** (add_count + 1)
