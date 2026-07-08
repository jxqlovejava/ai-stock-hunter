# -*- coding: utf-8 -*-
"""Signal and PortfolioTarget — LEAN-inspired separation of prediction from execution.

Signal carries the *what* and *why* (Insight in LEAN terms).
PortfolioTarget carries the *how much* (the portfolio-level ordering decision).

This decoupling lets:
- Different models emit Signals without caring about portfolio state.
- A separate allocation layer (PositioningEngine) convert Signals into targets.
- The SignalTracker close the confidence-calibration feedback loop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Direction(str, Enum):
    """Predicted price direction for a signal."""

    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


# ---------------------------------------------------------------------------
# Signal — pure prediction (LEAN Insight equivalent)
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    """A price-direction prediction, separated from position sizing.

    Fields
    ------
    symbol : str
        Stock code (e.g. "000001.SZ").
    direction : Direction
        Predicted direction: UP, DOWN, or FLAT.
    confidence : float
        Model confidence in the prediction, 0.0–1.0.
    source_model : str
        Name of the model/engine that produced this signal
        (e.g. "verdict_engine", "momentum_scanner", "alpha_lens").
    created_at : datetime
        When the signal was generated.
    magnitude : float | None
        Predicted percentage change over the time horizon, nullable.
    weight : float | None
        Portfolio allocation hint expressed as a fraction of total
        portfolio value, 0.0–1.0.  None means "let the allocator decide".
    time_horizon : str
        Prediction horizon: "short" / "medium" / "long".
    signal_id : str
        Unique identifier, auto-generated.
    metadata : dict
        Extra context (e.g. raw scores, risk flags, citations).
    """

    symbol: str
    direction: Direction
    confidence: float
    source_model: str
    created_at: datetime = field(default_factory=datetime.now)
    magnitude: Optional[float] = None
    weight: Optional[float] = None
    time_horizon: str = "medium"
    signal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PortfolioTarget — execution / position-sizing side
# ---------------------------------------------------------------------------


@dataclass
class PortfolioTarget:
    """A target position derived from a Signal.

    Positive *quantity* = buy / go long.
    Negative *quantity* = sell / go short.
    Zero *quantity* = close the position (flat).

    Fields
    ------
    symbol : str
        Stock code.
    quantity : float
        Number of shares to trade (sign encodes direction).
    target_weight : float
        Desired allocation as a fraction of portfolio, 0.0–1.0.
    reason : str
        Human-readable explanation for this target.
    source_signal_id : str
        Reference back to the originating Signal.
    created_at : datetime
        When this target was created.
    """

    symbol: str
    quantity: float
    target_weight: float
    reason: str
    source_signal_id: str
    created_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# SignalScore — evaluation result for the calibration feedback loop
# ---------------------------------------------------------------------------


@dataclass
class SignalScore:
    """Result of evaluating a Signal against actual price movement."""

    signal_id: str
    predicted_direction: Direction
    actual_return: float
    direction_correct: bool
    magnitude_error: Optional[float] = None
    evaluated_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# SignalTracker — stores signals for confidence calibration
# ---------------------------------------------------------------------------


class SignalTracker:
    """In-memory store of signals for the confidence-calibration feedback loop.

    Tracks all generated signals and lets consumers evaluate them against
    realised prices, then query per-symbol or global direction accuracy.
    """

    def __init__(self) -> None:
        self._signals: dict[str, Signal] = {}
        self._scores: dict[str, SignalScore] = {}
        self._symbol_signals: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Write side
    # ------------------------------------------------------------------

    def track(self, signal: Signal) -> None:
        """Store *signal* for later evaluation.

        Args:
            signal: The Signal to track.
        """
        self._signals[signal.signal_id] = signal
        self._symbol_signals.setdefault(signal.symbol, []).append(signal.signal_id)

    # ------------------------------------------------------------------
    # Evaluation (called when the actual outcome is known)
    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        actual_price: float,
        ref_price: Optional[float] = None,
        as_of: Optional[datetime] = None,
    ) -> Optional[SignalScore]:
        """Evaluate the latest signal for *symbol* against the realised price.

        Args:
            symbol: Stock code.
            actual_price: Current market price.
            ref_price: Reference price at signal creation.
                       If None, uses the signal's ``reference_price`` from
                       metadata, or defaults to a placeholder 0.0.
            as_of: Evaluation timestamp. Defaults to ``datetime.now()``.

        Returns:
            SignalScore if a signal exists for *symbol*, else None.
        """
        signal_ids = self._symbol_signals.get(symbol, [])
        if not signal_ids:
            return None

        latest_id = signal_ids[-1]
        signal = self._signals[latest_id]
        as_of = as_of or datetime.now()

        # Determine reference price
        ref = ref_price or signal.metadata.get("reference_price", 0.0)
        actual_return = (actual_price - ref) / ref if ref else 0.0

        # Direction correctness
        if signal.direction == Direction.FLAT:
            direction_correct = abs(actual_return) < 0.01
        else:
            intended_sign = 1 if signal.direction == Direction.UP else -1
            direction_correct = (actual_return * intended_sign) > 0

        magnitude_error = None
        if signal.magnitude is not None:
            magnitude_error = abs(signal.magnitude - actual_return)

        score = SignalScore(
            signal_id=signal.signal_id,
            predicted_direction=signal.direction,
            actual_return=actual_return,
            direction_correct=direction_correct,
            magnitude_error=magnitude_error,
            evaluated_at=as_of,
        )
        self._scores[signal.signal_id] = score
        return score

    # ------------------------------------------------------------------
    # Accuracy queries
    # ------------------------------------------------------------------

    def get_accuracy(self, symbol: Optional[str] = None) -> float:
        """Direction accuracy rate (0.0–1.0).

        Args:
            symbol: If provided, only signals for this symbol are considered.
                    Otherwise, all evaluated signals are included.

        Returns:
            Fraction of evaluated signals whose direction was correct.
            Returns 0.0 when there are no evaluated signals.
        """
        if symbol:
            signal_ids = self._symbol_signals.get(symbol, [])
        else:
            signal_ids = list(self._scores.keys())

        evaluated = [sid for sid in signal_ids if sid in self._scores]
        if not evaluated:
            return 0.0

        correct = sum(1 for sid in evaluated if self._scores[sid].direction_correct)
        return correct / len(evaluated)

    def get_signal(self, signal_id: str) -> Optional[Signal]:
        """Retrieve a tracked signal by its ID."""
        return self._signals.get(signal_id)

    def get_score(self, signal_id: str) -> Optional[SignalScore]:
        """Retrieve the evaluation score for a signal, if evaluated."""
        return self._scores.get(signal_id)

    @property
    def total_signals(self) -> int:
        """Total number of tracked signals."""
        return len(self._signals)

    @property
    def evaluated_count(self) -> int:
        """Number of signals that have been evaluated."""
        return len(self._scores)


# ---------------------------------------------------------------------------
# Helper: verdict → Signal converter
# ---------------------------------------------------------------------------


def signal_from_verdict(
    verdict: "Verdict",  # noqa: F821 — circular-safe string annotation
    source_model: str = "verdict_engine",
    time_horizon: str = "medium",
) -> Signal:
    """Convert a Verdict into a Signal.

    Maps the Verdict's recommendation to a Direction:

        BUY / ADD  →  UP
        HOLD       →  FLAT
        REDUCE / SELL  →  DOWN

    The Verdict's confidence, score, and alpha rationale are carried over
    into the Signal's metadata for full traceability.
    """
    # Recommendation → Direction
    rec = verdict.recommendation.upper()
    if rec in ("BUY", "ADD"):
        direction = Direction.UP
    elif rec in ("REDUCE", "SELL"):
        direction = Direction.DOWN
    else:
        direction = Direction.FLAT

    # Bundle full context into metadata for auditability
    metadata = {
        "verdict_score": verdict.score,
        "recommendation": verdict.recommendation,
        "risks": list(verdict.risks),
        "falsifiable": list(verdict.falsifiable),
        "alpha_rationale": verdict.alpha_rationale,
        "consensus_challenge": verdict.consensus_challenge,
        "game_theory_risks": list(verdict.game_theory_risks),
        "mental_model_fit_score": verdict.mental_model_fit_score,
        "mental_model_warnings": list(verdict.mental_model_warnings),
        "source_citations": list(verdict.source_citations),
    }

    return Signal(
        symbol=verdict.symbol,
        direction=direction,
        confidence=verdict.confidence,
        source_model=source_model,
        time_horizon=time_horizon,
        magnitude=None,  # Verdict does not emit magnitude — leave for specialised models
        weight=verdict.score / 100.0,  # rough allocation hint
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Helper: Signal → PortfolioTarget converter
# ---------------------------------------------------------------------------


def target_from_signal(
    signal: Signal,
    portfolio_value: float,
    current_price: float,
    reason: Optional[str] = None,
    max_weight: float = 1.0,
) -> PortfolioTarget:
    """Convert a Signal into a concrete PortfolioTarget.

    The target weight is determined by:

    1. The signal's explicit ``weight`` hint (if set and within bounds).
    2. Otherwise, ``signal.weight = signal.confidence * 0.5`` as a sensible
       default (half the portfolio at full confidence).

    The quantity is then ``target_weight * portfolio_value / current_price``.
    A negative sign is applied when ``direction == DOWN``.
    Zero when ``direction == FLAT``.

    Args:
        signal: The source Signal.
        portfolio_value: Total portfolio value in the same currency unit.
        current_price: Current market price of the asset.
        reason: Optional override for the reason text. Auto-generated when
                None.
        max_weight: Maximum allowed allocation (0.0–1.0). Defaults to 1.0.

    Returns:
        A PortfolioTarget ready for execution.
    """
    # Resolve target weight
    if signal.weight is not None and 0.0 <= signal.weight <= max_weight:
        target_weight = signal.weight
    else:
        target_weight = min(signal.confidence * 0.5, max_weight)

    # Direction → quantity sign
    if signal.direction == Direction.UP:
        quantity_sign = 1.0
    elif signal.direction == Direction.DOWN:
        quantity_sign = -1.0
    else:  # FLAT
        quantity_sign = 0.0

    quantity = quantity_sign * target_weight * portfolio_value / current_price if current_price else 0.0

    if reason is None:
        reason = (
            f"{signal.source_model}: {signal.direction.value} "
            f"(conf={signal.confidence:.2f}, weight={target_weight:.1%})"
        )

    return PortfolioTarget(
        symbol=signal.symbol,
        quantity=round(quantity, 4),
        target_weight=round(target_weight, 4),
        reason=reason,
        source_signal_id=signal.signal_id,
    )
