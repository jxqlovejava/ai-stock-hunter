# -*- coding: utf-8 -*-
"""Adapter that wraps the existing ``DoctrineChecker`` as a ``RiskManagementModel``.

``DoctrineRiskModel``
    Runs the 31 military doctrine rules against each portfolio target.
    Block-level violations zero the target weight; warn-level violations
    apply a configurable weight penalty (default 50 % reduction).
"""

from __future__ import annotations

import logging
from typing import Callable

from .protocols import (
    AlgorithmContext,
    PortfolioTarget,
    RiskManagementModel,
    SignalDirection,
)

logger = logging.getLogger(__name__)


class DoctrineRiskModel:
    """Adapter that wraps ``DoctrineChecker`` as a ``RiskManagementModel``.

    On each call to ``manage_risk()``, the underlying ``DoctrineChecker``
    is invoked for every symbol in the target list.  The doctrine result
    drives risk adjustments:

    *Block-level violations*
        Target weight is set to 0.0 (symbol excluded from portfolio).

    *Warn-level violations*
        Target weight is multiplied by ``warn_penalty`` (default 0.5).

    *Info-level violations*
        No adjustment — only logged.

    Usage::

        from src.doctrine.checker import DoctrineChecker
        from src.routing.models import DoctrineRiskModel

        risk = DoctrineRiskModel(checker)
        safe_targets = risk.manage_risk(algorithm, targets)

    The optional ``context_fn`` callback lets callers inject dynamic
    context (e.g. market regime, sector exposure) into the doctrine
    check for each symbol.
    """

    def __init__(
        self,
        checker,
        warn_penalty: float = 0.50,
        enabled_rules: set[str] | None = None,
        context_fn: Callable[[str, AlgorithmContext], dict] | None = None,
    ) -> None:
        """
        Args:
            checker:  A ``DoctrineChecker`` instance (duck-typed; expected
                      to have a ``check(symbol, context, enabled_rules)``
                      method returning a ``DoctrineResult``).
            warn_penalty:  Weight multiplier applied per warn-level
                           violation (``1.0`` = no penalty; ``0.0`` = zero).
            enabled_rules:  Optional set of rule IDs to enable.
                            ``None`` = all rules active.
            context_fn:  Optional callback ``(symbol, algorithm) -> dict``
                         that returns context passed to ``DoctrineChecker.check()``.
                         When omitted, the algorithm's portfolio dict is used.
        """
        self._checker = checker
        self._warn_penalty = warn_penalty
        self._enabled_rules = enabled_rules
        self._context_fn = context_fn

    def manage_risk(
        self,
        algorithm: AlgorithmContext,
        targets: list[PortfolioTarget],
    ) -> list[PortfolioTarget]:
        """Check every target symbol against the doctrine rules.

        Returns a new list of ``PortfolioTarget`` with adjusted weights.
        Targets with weight == 0 after adjustment **are kept** (they
        serve as explicit "flatten" instructions to downstream models).
        """
        adjusted: list[PortfolioTarget] = []

        for t in targets:
            # 1. build context for this symbol
            ctx = algorithm.portfolio.copy()
            ctx["symbol"] = t.symbol

            if self._context_fn is not None:
                extra = self._context_fn(t.symbol, algorithm)
                if isinstance(extra, dict):
                    ctx.update(extra)

            # 2. run doctrine check
            result = self._checker.check(
                symbol=t.symbol,
                context=ctx,
                enabled_rules=self._enabled_rules,
            )

            # 3. apply risk adjustments
            new_weight = t.weight

            if not result.passed:
                # block-level violations → zero out
                blocked_names = [r.name for r in result.blocked_by]
                logger.info(
                    "DoctrineRiskModel zeroing %s (blocked by: %s)",
                    t.symbol, "; ".join(blocked_names),
                )
                new_weight = 0.0

            if result.warnings:
                warn_names = [r.name for r in result.warnings]
                penalty = self._warn_penalty ** len(result.warnings)
                new_weight *= penalty
                logger.info(
                    "DoctrineRiskModel penalised %s by %.2f (warnings: %s)",
                    t.symbol, penalty, "; ".join(warn_names),
                )

            adjusted.append(PortfolioTarget(
                symbol=t.symbol,
                weight=round(new_weight, 6),
                direction=t.direction,
                tags={
                    **t.tags,
                    "doctrine_passed": result.passed,
                    "doctrine_blocked": [r.id for r in result.blocked_by],
                    "doctrine_warnings": [r.id for r in result.warnings],
                    "doctrine_infos": [r.id for r in result.infos],
                },
            ))

        return adjusted

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}"
            f"(warn_penalty={self._warn_penalty}, "
            f"enabled_rules={self._enabled_rules})"
        )
