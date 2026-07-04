# -*- coding: utf-8 -*-
"""回测模块 — Backtrader 封装。"""

from .comparator import StrategyComparator, StrategyRanking
from .engine import BacktestEngine, BacktestResult
from .mvp1_strategy import MVP1Strategy
from .optimizer import (
    BayesianOptimizer,
    GridSearchOptimizer,
    OptimizationResult,
)
from .strategy_registry import StrategyRegistry, StrategyVersion

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "MVP1Strategy",
    "GridSearchOptimizer",
    "BayesianOptimizer",
    "OptimizationResult",
    "StrategyRegistry",
    "StrategyVersion",
    "StrategyComparator",
    "StrategyRanking",
]
