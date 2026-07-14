# -*- coding: utf-8 -*-
"""Strategy engine package — trade generation and position management."""
from .engine import StrategyEngine
from .types import AddCheckResult, ExitCheckResult, PortfolioSnapshot, PositionSize, StrategySignal

try:
    from .sizing import PositionSizer
except ImportError:
    PositionSizer = None
try:
    from .exit_rules import ExitRuleEngine
except ImportError:
    ExitRuleEngine = None
try:
    from .add_rules import AddRuleEngine
except ImportError:
    AddRuleEngine = None

try:
    from .entry_templates import ALL_TEMPLATES, trend_following, mean_reversion, momentum_breakout
    from .entry_templates import volatility_expansion, capital_inflow, sector_resonance, dragon_tiger
except ImportError:
    ALL_TEMPLATES = {}
    trend_following = mean_reversion = momentum_breakout = None
    volatility_expansion = capital_inflow = sector_resonance = dragon_tiger = None

try:
    from .data_adapter import MarketDataAdapter
except ImportError:
    MarketDataAdapter = None

try:
    from .signal_filter import SignalQualityFilter, FilterResult
except ImportError:
    SignalQualityFilter = None
    FilterResult = None

try:
    from .board_lot import BOARD_LOT, resolve_sell_quantity, resolve_buy_quantity
    from .swing_overlay import (
        SwingOverlayEngine,
        SwingOverlayConfig,
        OverlayAction,
        OverlayDecision,
        OverlayMarketContext,
        PositionBucketView,
        BucketPlan,
        format_decision,
    )
    from .overlay_integration import (
        evaluate_overlay,
        decision_to_paper_order,
        wrap_signal_engine_with_overlay,
        adjust_target_weights_with_overlay,
    )
except ImportError:
    BOARD_LOT = 100
    resolve_sell_quantity = resolve_buy_quantity = None
    SwingOverlayEngine = SwingOverlayConfig = None
    OverlayAction = OverlayDecision = OverlayMarketContext = None
    PositionBucketView = BucketPlan = format_decision = None
    evaluate_overlay = decision_to_paper_order = None
    wrap_signal_engine_with_overlay = adjust_target_weights_with_overlay = None

__all__ = [
    "StrategyEngine", "PositionSizer", "ExitRuleEngine", "AddRuleEngine",
    "SignalQualityFilter", "FilterResult",
    "StrategySignal", "PositionSize", "ExitCheckResult", "AddCheckResult",
    "PortfolioSnapshot", "MarketDataAdapter",
    # 入场模板
    "ALL_TEMPLATES",
    "trend_following", "mean_reversion", "momentum_breakout",
    "volatility_expansion", "capital_inflow", "sector_resonance", "dragon_tiger",
    # V1/V2 持仓 overlay
    "BOARD_LOT", "resolve_sell_quantity", "resolve_buy_quantity",
    "SwingOverlayEngine", "SwingOverlayConfig",
    "OverlayAction", "OverlayDecision", "OverlayMarketContext",
    "PositionBucketView", "BucketPlan", "format_decision",
    "evaluate_overlay", "decision_to_paper_order",
    "wrap_signal_engine_with_overlay", "adjust_target_weights_with_overlay",
]
