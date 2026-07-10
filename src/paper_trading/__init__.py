# -*- coding: utf-8 -*-
"""模拟交易模块 — 自包含 A 股实盘模拟交易引擎。

核心分析/策略/风控全部复用现有路由管道 (Orchestrator → PositioningEngine → RiskControlEngine)，
此模块仅提供薄调度层：状态管理 / 候选筛选 / 订单执行模拟 / 报告生成。

入口:
    from src.paper_trading import PaperTradingEngine
    engine = PaperTradingEngine()
    result = engine.run_daily_cycle()

CLI:
    python -m src paper-trade start     # 初始化/恢复模拟交易
    python -m src paper-trade run       # 手动执行每日循环
    python -m src paper-trade status    # 查看组合状态
    python -m src paper-trade report    # 生成报告
    python -m src paper-trade review    # 触发复盘
    python -m src paper-trade history   # 交易历史
    python -m src paper-trade reset     # 重置账户
"""

from .config import (
    PaperTradingConfig,
    PaperTradingConfigManager,
    PositionLimits,
    RiskProfile,
    InvestmentGoal,
    TradingStyle,
    HoldingPeriod,
)
from .engine import DailyResult, PaperTradingEngine
from .order_factory import OrderFactory, PaperOrder
from .reporter import ReportGenerator
from .scheduler import (
    is_trading_day,
    next_trading_day,
    prev_trading_day,
    trading_days_in_range,
    today_str,
)
from .state import (
    PaperTrade,
    PortfolioState,
    PortfolioStateManager,
)

# 保留旧有 mx-moni 桥接 (标记 deprecated)
from .bridge import PaperTradingBridge, PaperTradeResult, PaperTradingSession
from .signal_adapter import SignalAdapter, MoniOrder

__all__ = [
    # 核心引擎
    "PaperTradingEngine",
    "DailyResult",
    # 配置
    "PaperTradingConfig",
    "PaperTradingConfigManager",
    "PositionLimits",
    "RiskProfile",
    "InvestmentGoal",
    "TradingStyle",
    "HoldingPeriod",
    # 状态
    "PortfolioState",
    "PortfolioStateManager",
    "PaperTrade",
    # 订单
    "OrderFactory",
    "PaperOrder",
    # 报告
    "ReportGenerator",
    # 调度
    "is_trading_day",
    "next_trading_day",
    "prev_trading_day",
    "trading_days_in_range",
    "today_str",
    # 旧有 (deprecated)
    "PaperTradingBridge",
    "PaperTradeResult",
    "PaperTradingSession",
    "SignalAdapter",
    "MoniOrder",
]
