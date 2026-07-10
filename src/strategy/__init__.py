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

__all__ = [
    "StrategyEngine", "PositionSizer", "ExitRuleEngine", "AddRuleEngine",
    "StrategySignal", "PositionSize", "ExitCheckResult", "AddCheckResult",
    "PortfolioSnapshot",
    # 入场模板
    "ALL_TEMPLATES",
    "trend_following", "mean_reversion", "momentum_breakout",
    "volatility_expansion", "capital_inflow", "sector_resonance", "dragon_tiger",
]
