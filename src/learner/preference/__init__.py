# -*- coding: utf-8 -*-
"""投资者偏好模块 — 前向约束与偏好。

导出:
  - InvestorPreference / RiskProfile / InvestmentGoal / TradingStyle / InvestorTier
  - PositionLimits / CircleOfCompetence / ScoreWeights
  - InvestorPreferenceLoader
  - PreferenceAdapter (resolve_weights / resolve_rule_filter / resolve_position_limits / etc.)
"""

from __future__ import annotations

from .adapter import (
    is_board_accessible,
    resolve_board_filter,
    resolve_competence_penalty,
    resolve_macro_cap_multiplier,
    resolve_position_limits,
    resolve_rule_filter,
    resolve_weights,
)
from .loader import InvestorPreferenceLoader
from .model import (
    BoardAccess,
    CircleOfCompetence,
    InvestmentGoal,
    InvestorPreference,
    InvestorTier,
    PositionLimits,
    RiskProfile,
    ScoreWeights,
    TradingStyle,
    get_board_from_symbol,
)

# 向后兼容：PreferenceAdapter 作为模块级命名空间
class PreferenceAdapter:
    """偏好适配器命名空间 — 纯函数集合。"""
    resolve_weights = staticmethod(resolve_weights)
    resolve_rule_filter = staticmethod(resolve_rule_filter)
    resolve_position_limits = staticmethod(resolve_position_limits)
    resolve_macro_cap_multiplier = staticmethod(resolve_macro_cap_multiplier)
    resolve_competence_penalty = staticmethod(resolve_competence_penalty)
    resolve_board_filter = staticmethod(resolve_board_filter)
    is_board_accessible = staticmethod(is_board_accessible)


__all__ = [
    "BoardAccess",
    "InvestorPreference",
    "RiskProfile",
    "InvestmentGoal",
    "TradingStyle",
    "InvestorTier",
    "PositionLimits",
    "CircleOfCompetence",
    "ScoreWeights",
    "InvestorPreferenceLoader",
    "PreferenceAdapter",
    "get_board_from_symbol",
    "resolve_weights",
    "resolve_rule_filter",
    "resolve_position_limits",
    "resolve_macro_cap_multiplier",
    "resolve_competence_penalty",
    "resolve_board_filter",
    "is_board_accessible",
]
