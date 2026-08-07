# -*- coding: utf-8 -*-
"""回测模块 — BaizeCerebro 统一编排器 + Backtrader 兼容封装。

轻量核心 (cerebro/broker/result/strategy, 不含 backtrader) 总是可用；
重依赖子模块 (comparator/engine/mvp/optimizer 等, 依赖 backtrader) 在
缺失依赖时降级跳过 — 保证轻量环境 (如 Hermes 只装 pandas 的部署) 仍能
`from src.backtest.cost_model import AShareCostCalculator`, 不因 backtrader
缺失阻断整个包。
"""

from .cerebro import BaizeCerebro, BaizeDataFeed
from .strategy import BaizeStrategy
from .broker import BaizeBroker
from .result import BaizeResult, Order, OrderStatus, OrderType, TradeRecord

__all__ = [
    # 新 Cerebro 架构 (轻量核心, 无 backtrader 依赖)
    "BaizeCerebro",
    "BaizeDataFeed",
    "BaizeStrategy",
    "BaizeBroker",
    "BaizeResult",
    "Order",
    "OrderStatus",
    "OrderType",
    "TradeRecord",
]

# ── 重依赖子模块 (依赖 backtrader) — 缺依赖时降级跳过 ──
try:
    from .comparator import StrategyComparator, StrategyRanking
    from .competitor_benchmark import (
        BenchmarkResult,
        CompetitorAnalyzer,
        CompetitorProfile,
        PKReport,
    )
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
    from .walkforward import (
        WalkForwardConfig,
        WalkForwardOptimizer,
        WalkForwardResult,
    )
    from .verdict_strategy import VerdictBacktestStrategy
    from .verdict_factors import (
        compute_verdict_factors,
        WEIGHTS as VERDICT_WEIGHTS,
    )

    __all__ += [
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
except ImportError:
    # 环境缺 backtrader (如 Hermes 轻量部署) — 轻量核心仍可用
    pass
