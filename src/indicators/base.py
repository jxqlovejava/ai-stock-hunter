# -*- coding: utf-8 -*-
"""Indicator base classes — LEAN-inspired design for A-stock analysis.

Defines the hierarchy:
    Indicator (abstract)
    └── WindowIndicator  (rolling window of values)
        └── BarIndicator  (OHLC bar window)
            └── CandlestickPattern  (returns +1/0/-1)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class CandleSettings:
    """Thresholds for candlestick pattern recognition.

    All thresholds are expressed as fractions of the candle's total range
    (high - low). Defaults are typical LEAN values.
    """

    body_short: float = 0.10       # body < 10% range => short/doji-like
    body_long: float = 0.30        # body > 30% range => long/strong
    shadow_short: float = 0.10     # shadow < 10% range => negligible
    shadow_long: float = 0.30      # shadow > 30% range => noteworthy
    near: float = 0.10             # within 10% of reference => "near"
    far: float = 0.30              # beyond 30% of reference => "far"
    equality: float = 0.01         # tolerance for "equal" comparisons

    def __post_init__(self):
        # Ensure defaults don't conflict
        assert self.body_short < self.body_long, "body_short must be < body_long"
        assert self.shadow_short < self.shadow_long, "shadow_short must be < shadow_long"
        assert self.near < self.far, "near must be < far"


# ---------------------------------------------------------------------------
# Base indicator hierarchy
# ---------------------------------------------------------------------------


class Indicator(ABC):
    """Base class for all indicators.

    Each indicator maintains internal state and exposes:
        - is_ready: whether enough data has been seen
        - current_value: the latest computed value
        - source_citations: provenance tracking (see guardrails.md)
    """

    def __init__(self) -> None:
        self._is_ready = False
        self._current_value: Any = None
        self._source_citations: list[dict] = []
        self._name: str = self.__class__.__name__

    # ── public properties ──────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """True once the indicator has consumed enough data."""
        return self._is_ready

    @property
    def current_value(self) -> Any:
        """Latest computed value (None if not ready)."""
        return self._current_value

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def source_citations(self) -> list[dict]:
        """Read-only list of data provenance records."""
        return list(self._source_citations)

    # ── lifecycle ──────────────────────────────────────────────────────

    @abstractmethod
    def update(self, *args: Any, **kwargs: Any) -> None:
        """Feed new data and recompute."""

    def reset(self) -> None:
        """Clear all state, returning to pre-ready condition."""
        self._is_ready = False
        self._current_value = None
        self._source_citations.clear()

    # ── provenance helper ──────────────────────────────────────────────

    def _add_citation(
        self,
        provider: str = "indicator",
        field: str = "",
        confidence: float = 0.80,
        source_tier: str = "T2",
        nature: str = "interpretation",
        **extra: Any,
    ) -> None:
        self._source_citations.append(
            {
                "provider": provider,
                "field": field or self._name,
                "confidence": confidence,
                "source_tier": source_tier,
                "nature": nature,
                "fetch_timestamp": datetime.now().isoformat(),
                **extra,
            }
        )


class WindowIndicator(Indicator, Generic[T]):
    """Indicator backed by a fixed-length rolling window of raw values.

    Subclasses implement ``compute_next_value(window)`` which is called
    automatically when the window is full.
    """

    def __init__(self, period: int) -> None:
        super().__init__()
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self.period = period
        self.window: list[T] = []

    def update(self, value: T) -> None:
        self.window.append(value)
        if len(self.window) > self.period:
            self.window.pop(0)
        if len(self.window) >= self.period:
            self._is_ready = True
            self._current_value = self.compute_next_value(list(self.window))

    @abstractmethod
    def compute_next_value(self, window: list[T]) -> Any:
        """Compute the indicator value from the current window contents.

        Subclasses must override.  The window is a snapshot — mutations
        will not affect the internal rolling buffer.
        """

    def reset(self) -> None:
        super().reset()
        self.window.clear()


class BarIndicator(WindowIndicator[tuple]):
    """Indicator that operates on OHLC(V) bar tuples.

    Bar format: ``(open, high, low, close[, volume])``

    Convenience methods let callers pass dicts or named tuples.
    """

    def __init__(self, period: int = 1) -> None:
        super().__init__(period)

    def update(self, bar: tuple) -> None:
        """Push one OHLC bar.

        Args:
            bar: (open, high, low, close) or (open, high, low, close, volume)
        """
        super().update(bar)

    def update_from_dict(self, d: dict) -> None:
        """Push a bar from a dict with keys: open, high, low, close [, volume]."""
        bar = (
            d.get("open", 0.0),
            d.get("high", 0.0),
            d.get("low", 0.0),
            d.get("close", 0.0),
            d.get("volume", 0.0),
        )
        self.update(bar)


class CandlestickPattern(BarIndicator):
    """Base class for Japanese candlestick recognition.

    Returns:
        +1 (bullish signal)
         0 (no signal / pattern not found)
        -1 (bearish signal)
    """

    def __init__(self, name: str, period: int = 3) -> None:
        super().__init__(period)
        self._name = name
        self._current_value: int = 0

    def __repr__(self) -> str:
        return f"{self._name}({self._current_value})"


# ---------------------------------------------------------------------------
# Bar-level helpers (used extensively by candlestick patterns)
# ---------------------------------------------------------------------------

# Named indices into bar tuples
O: int = 0  # open
H: int = 1  # high
L: int = 2  # low
C: int = 3  # close
V: int = 4  # volume (optional)


def candle_range(bar: tuple) -> float:
    return bar[H] - bar[L]


def real_body(bar: tuple) -> float:
    return abs(bar[C] - bar[O])


def upper_shadow(bar: tuple) -> float:
    return bar[H] - max(bar[O], bar[C])


def lower_shadow(bar: tuple) -> float:
    return min(bar[O], bar[C]) - bar[L]


def is_bullish(bar: tuple) -> bool:
    return bar[C] > bar[O]


def is_bearish(bar: tuple) -> bool:
    return bar[C] < bar[O]


def body_midpoint(bar: tuple) -> float:
    """Average of open and close."""
    return (bar[O] + bar[C]) * 0.5


def candle_midpoint(bar: tuple) -> float:
    """Average of high and low."""
    return (bar[H] + bar[L]) * 0.5
