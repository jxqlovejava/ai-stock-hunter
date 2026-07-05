# -*- coding: utf-8 -*-
"""回测模块 — Backtrader 封装。"""

from .comparator import StrategyComparator, StrategyRanking
from .competitor_benchmark import BenchmarkResult, CompetitorAnalyzer, CompetitorProfile, PKReport
from .engine import BacktestEngine, BacktestResult
from .mvp1_strategy import MVP1Strategy
from .optimizer import (
    BayesianOptimizer,
    GridSearchOptimizer,
    OptimizationResult,
)
from .portfolio_optimizer import PortfolioOptimizer, PortfolioWeights
from .review import ReviewStats, TradeReview, TradeReviewer
from .strategy_registry import StrategyRegistry, StrategyVersion
from .visualizer import BacktestVisualizer
from .walkforward import WalkForwardConfig, WalkForwardOptimizer, WalkForwardResult

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
    "BacktestVisualizer",
    "WalkForwardOptimizer",
    "WalkForwardConfig",
    "WalkForwardResult",
    "PortfolioOptimizer",
    "PortfolioWeights",
    "CompetitorAnalyzer",
    "CompetitorProfile",
    "BenchmarkResult",
    "PKReport",
    "TradeReviewer",
    "TradeReview",
    "ReviewStats",
]
