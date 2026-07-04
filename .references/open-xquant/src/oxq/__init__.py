"""open-xquant — Agent First quantitative trading framework."""

__version__ = "0.1.0"

from oxq.core.registry import (
    list_indicators,
    list_portfolio_optimizers,
    list_rules,
    list_signals,
    register_indicator,
    register_portfolio_optimizer,
    register_rule,
    register_signal,
)

__all__ = [
    "__version__",
    "list_indicators",
    "list_portfolio_optimizers",
    "list_rules",
    "list_signals",
    "register_indicator",
    "register_portfolio_optimizer",
    "register_rule",
    "register_signal",
]
