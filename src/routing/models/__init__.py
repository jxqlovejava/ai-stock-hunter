# -*- coding: utf-8 -*-
"""Pluggable pipeline model interfaces — LEAN-inspired Protocol contracts.

Provides composable, testable abstractions for each stage of the
analysis-to-execution pipeline:

  AlphaModel               -> list[Signal]
  PortfolioConstructionModel -> list[PortfolioTarget]
  RiskManagementModel      -> list[PortfolioTarget]
  ExecutionModel           -> list[Order]
  UniverseSelectionModel   -> list[str]
"""

from .protocols import (
    AlgorithmContext,
    AlphaModel,
    ExecutionModel,
    Order,
    OrderSide,
    PortfolioConstructionModel,
    PortfolioTarget,
    RiskManagementModel,
    Signal,
    SignalDirection,
    UniverseSelectionModel,
)
from .composite import CompositeAlphaModel, CompositeRiskModel
from .doctrine_adapter import DoctrineRiskModel

__all__ = [
    # -- data models --
    "AlgorithmContext",
    "Order",
    "OrderSide",
    "PortfolioTarget",
    "Signal",
    "SignalDirection",
    # -- protocols --
    "AlphaModel",
    "ExecutionModel",
    "PortfolioConstructionModel",
    "RiskManagementModel",
    "UniverseSelectionModel",
    # -- composites --
    "CompositeAlphaModel",
    "CompositeRiskModel",
    # -- adapters --
    "DoctrineRiskModel",
]
