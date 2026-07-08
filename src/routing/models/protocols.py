# -*- coding: utf-8 -*-
"""Protocol definitions for the pluggable pipeline model interfaces.

Each protocol mirrors a LEAN engine stage but adapted to the Baize
A-share context.  Implementations are free to add their own __init__
parameters — these Protocols only dictate the stage-contract signature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class SignalDirection(IntEnum):
    """Direction of an Alpha signal.

    Mirrors LEAN's ``InsightDirection``:
      ``UP=1``   — long / bullish
      ``DOWN=-1`` — short / bearish
      ``FLAT=0``  — neutral / no position
    """

    DOWN = -1
    FLAT = 0
    UP = 1


class OrderSide(str, Enum):
    """Order side — BUY or SELL."""
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Signal:
    """Output of an ``AlphaModel``.

    Carries the model's conviction about a single symbol together with
    provenance metadata required by the Baize data-provenance rules.
    """

    symbol: str
    direction: SignalDirection
    magnitude: float = 0.0       # expected return magnitude (0.0 … 1.0)
    confidence: float = 0.5      # 0.0 … 1.0
    source: str = ""              # model name / identifier
    timestamp: datetime = field(default_factory=datetime.now)

    # Baize provenance (see guardrails.md)
    source_citations: list = field(default_factory=list)
    tier: str = "T2"             # primary/secondary/tertiary shorthand
    nature: str = "interpretation"  # fact / interpretation / speculation


@dataclass(frozen=True)
class PortfolioTarget:
    """Output of ``PortfolioConstructionModel`` (and adjusted by ``RiskManagementModel``).

    Describes the desired allocation for a single symbol.
    """

    symbol: str
    weight: float                # 0.0 … 1.0 as fraction of total portfolio
    direction: SignalDirection = SignalDirection.FLAT
    tags: dict = field(default_factory=dict)  # extensible metadata


@dataclass(frozen=True)
class Order:
    """Output of ``ExecutionModel`` — a concrete order ready to send to the broker."""

    symbol: str
    quantity: int                # positive = buy, negative = sell
    order_type: str = "MARKET"   # MARKET / LIMIT
    side: OrderSide = OrderSide.BUY
    limit_price: float | None = None
    tags: dict = field(default_factory=dict)  # broker-specific metadata


@dataclass
class AlgorithmContext:
    """Lightweight equivalent of LEAN's ``QCAlgorithm``.

    Carries the full state available to every pipeline stage: current
    portfolio snapshot, market condition map, and any fetched data.
    Hand-edited between stages — no immutability guarantee.
    """

    portfolio: dict = field(default_factory=dict)
    market: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class AlphaModel(Protocol):
    """Generates trading signals from raw data.

    ``update()`` is called each time new data arrives (e.g. every bar).

    Returns a (possibly empty) list of ``Signal`` — one per symbol that
    the model has conviction about during this tick.
    """

    def update(
        self,
        algorithm: AlgorithmContext,
        data: dict,
    ) -> list[Signal]:
        ...


@runtime_checkable
class PortfolioConstructionModel(Protocol):
    """Maps alpha signals into target portfolio weights.

    ``create_targets()`` receives all active signals and returns the
    desired allocation for each symbol.  The implementation is
    responsible for:

    - normalising weights (the sum may exceed 1.0)
    - respecting any portfolio-level constraints (sector caps, etc.)
    - handling flat/neutral signals
    """

    def create_targets(
        self,
        algorithm: AlgorithmContext,
        signals: list[Signal],
    ) -> list[PortfolioTarget]:
        ...


@runtime_checkable
class RiskManagementModel(Protocol):
    """Adjusts portfolio targets to respect risk limits.

    ``manage_risk()`` receives the targets produced by the portfolio
    construction model and returns an adjusted list.  Typical adjustments:

    - zeroing targets that violate hard risk limits
    - reducing targets that exceed position-size constraints
    - applying volatility-based scaling

    The model may also produce *new* targets (e.g. for hedging).
    """

    def manage_risk(
        self,
        algorithm: AlgorithmContext,
        targets: list[PortfolioTarget],
    ) -> list[PortfolioTarget]:
        ...


@runtime_checkable
class ExecutionModel(Protocol):
    """Translates portfolio targets into broker orders.

    ``execute()`` is called every time new targets are ready.  The model
    decides *how* to fill the gap between current and desired positions
    (market orders, limit orders, TWAP, etc.).
    """

    def execute(
        self,
        algorithm: AlgorithmContext,
        targets: list[PortfolioTarget],
    ) -> list[Order]:
        ...


@runtime_checkable
class UniverseSelectionModel(Protocol):
    """Selects the set of symbols to include in the pipeline for the next tick.

    ``select_universe()`` returns a list of symbol strings that the
    pipeline should process.  An empty list means no changes.
    """

    def select_universe(
        self,
        algorithm: AlgorithmContext,
    ) -> list[str]:
        ...
