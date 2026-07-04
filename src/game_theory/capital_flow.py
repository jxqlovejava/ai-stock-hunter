# -*- coding: utf-8 -*-
"""规则→资金流因果模型（原则 3）。

从 game_theory/rules.py 中提取的 TOP_3_RULES 数据模型。
Phase 2: 框架已就绪，待接入实时数据进行 Granger 因果检验。
"""

from __future__ import annotations

# Re-export from rules.py for backward compatibility
from .rules import TOP_3_RULES, RuleCapitalFlowModel

__all__ = ["TOP_3_RULES", "RuleCapitalFlowModel"]
