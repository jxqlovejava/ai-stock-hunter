# -*- coding: utf-8 -*-
"""回测模块 — BaizeCerebro 统一编排器 + Backtrader 兼容封装。"""

from .cerebro import BaizeCerebro, BaizeDataFeed
from .strategy import BaizeStrategy
from .broker import BaizeBroker
from .result import BaizeResult, Order, OrderStatus, OrderType, TradeRecord

from .comparator import StrategyComparator, StrategyRanking
from .competitor_benchmark import BenchmarkResult, CompetitorAnalyzer, CompetitorProfile, PKReport
from .engine import BacktestEngine, BacktestResult
from .intraday_engine import (
    Holding,
    IntradayEngine,
    IntradayResult,
    IntradayStrategy,
    Order as IntradayOrder,
    OrderDirection,
    OrderHandler,
    OrderStatus as IntradayOrderStatus,
    Portfolio,
)
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

from .verdict_strategy import VerdictBacktestStrategy
from .verdict_factors import compute_verdict_factors, WEIGHTS as VERDICT_WEIGHTS

__all__ = [
    # 新 Cerebro 架构
    "BaizeCerebro",
    "BaizeDataFeed",
    "BaizeStrategy",
    "BaizeBroker",
    "BaizeResult",
    "Order",
    "OrderStatus",
    "OrderType",
    "TradeRecord",
    # 兼容旧引擎
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
    # 日内回测
    "IntradayEngine",
    "IntradayResult",
    "IntradayStrategy",
    "Portfolio",
    "Holding",
    "OrderDirection",
    "OrderHandler",
    # Verdict 回测
    "VerdictBacktestStrategy",
    "compute_verdict_factors",
    "VERDICT_WEIGHTS",
]
