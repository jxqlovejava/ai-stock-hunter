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
    resolve_competence_penalty,
    resolve_macro_cap_multiplier,
    resolve_position_limits,
    resolve_rule_filter,
    resolve_weights,
)
from .loader import InvestorPreferenceLoader
from .model import (
    CircleOfCompetence,
    InvestmentGoal,
    InvestorPreference,
    InvestorTier,
    PositionLimits,
    RiskProfile,
    ScoreWeights,
    TradingStyle,
)

# 向后兼容：PreferenceAdapter 作为模块级命名空间
class PreferenceAdapter:
    """偏好适配器命名空间 — 纯函数集合。"""
    resolve_weights = staticmethod(resolve_weights)
    resolve_rule_filter = staticmethod(resolve_rule_filter)
    resolve_position_limits = staticmethod(resolve_position_limits)
    resolve_macro_cap_multiplier = staticmethod(resolve_macro_cap_multiplier)
    resolve_competence_penalty = staticmethod(resolve_competence_penalty)


__all__ = [
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
    "resolve_weights",
    "resolve_rule_filter",
    "resolve_position_limits",
    "resolve_macro_cap_multiplier",
    "resolve_competence_penalty",
]
