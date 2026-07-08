# -*- coding: utf-8 -*-
"""Composite model wrappers for the pipeline interfaces.

``CompositeAlphaModel``
    Aggregates signals from multiple ``AlphaModel`` instances and
    deduplicates by symbol (highest-confidence signal wins).

``CompositeRiskModel``
    Chains multiple ``RiskManagementModel`` instances.  Each subsequent
    model receives the output of the previous one and may further adjust
    or override targets.
"""

from __future__ import annotations

from typing import Sequence

from .protocols import (
    AlgorithmContext,
    AlphaModel,
    PortfolioTarget,
    RiskManagementModel,
    Signal,
)


# ---------------------------------------------------------------------------
# CompositeAlphaModel
# ---------------------------------------------------------------------------


class CompositeAlphaModel:
    """Aggregates multiple ``AlphaModel`` instances.

    On ``update()`` each child model is called in order.  If more than
    one model produces a signal for the same symbol, the signal with the
    **highest confidence** wins (other signals for that symbol are
    discarded).

    Usage::

        alpha = CompositeAlphaModel([
            MomentumAlphaModel(),
            MeanReversionAlphaModel(),
        ])
        signals = alpha.update(algorithm, data)
    """

    def __init__(self, alphas: Sequence[AlphaModel]) -> None:
        if not alphas:
            raise ValueError("CompositeAlphaModel requires at least one AlphaModel")
        self._alphas = list(alphas)

    def update(
        self,
        algorithm: AlgorithmContext,
        data: dict,
    ) -> list[Signal]:
        """Collect signals from all alphas, deduplicating by symbol.

        Returns a merged list where each symbol appears at most once.
        """
        merged: dict[str, Signal] = {}

        for alpha in self._alphas:
            signals = alpha.update(algorithm, data)
            for s in signals:
                existing = merged.get(s.symbol)
                if existing is None or s.confidence > existing.confidence:
                    merged[s.symbol] = s

        return list(merged.values())

    def __repr__(self) -> str:
        return f"{type(self).__name__}(alphas={self._alphas!r})"


# ---------------------------------------------------------------------------
# CompositeRiskModel
# ---------------------------------------------------------------------------


class CompositeRiskModel:
    """Chains multiple ``RiskManagementModel`` instances.

    Models are called **in order**.  Each model receives the output of
    the previous model.  Later models can override (zero out, reduce,
    or increase) targets produced by earlier models.

    A common pattern is to place general position-sizing constraints
    first, followed by doctrine / blacklist checks that can fully
    zero out targets.

    Usage::

        risk = CompositeRiskModel([
            MaxPositionSizeRisk(),
            DoctrineRiskModel(checker),
        ])
        safe_targets = risk.manage_risk(algorithm, targets)
    """

    def __init__(self, risks: Sequence[RiskManagementModel]) -> None:
        if not risks:
            raise ValueError("CompositeRiskModel requires at least one RiskManagementModel")
        self._risks = list(risks)

    def manage_risk(
        self,
        algorithm: AlgorithmContext,
        targets: list[PortfolioTarget],
    ) -> list[PortfolioTarget]:
        """Run each risk model in sequence, threading targets through."""
        current = targets
        for risk in self._risks:
            current = risk.manage_risk(algorithm, current)
        return current

    def __repr__(self) -> str:
        return f"{type(self).__name__}(risks={self._risks!r})"
