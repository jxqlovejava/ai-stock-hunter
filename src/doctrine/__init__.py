# -*- coding: utf-8 -*-
"""军规引擎 — 30 条 A 股专属投资军规。"""

from .checker import DoctrineChecker
from .rules import MILITARY_RULES, Rule, RuleCategory, Severity

__all__ = ["DoctrineChecker", "MILITARY_RULES", "Rule", "RuleCategory", "Severity"]
