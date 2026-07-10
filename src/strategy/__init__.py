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

__all__ = [
    "StrategyEngine", "PositionSizer", "ExitRuleEngine", "AddRuleEngine",
    "StrategySignal", "PositionSize", "ExitCheckResult", "AddCheckResult",
    "PortfolioSnapshot",
]
