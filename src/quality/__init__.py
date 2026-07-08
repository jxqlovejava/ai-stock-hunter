# -*- coding: utf-8 -*-
"""质量审查模块 — 借鉴 CogAlpha 论文的多 Agent 质量审查器。

Multi-Agent Quality Checker 对 诊断报告执行 5 维度审查:
  1. DataFreshness    — 数据新鲜度
  2. Consistency      — 内部一致性
  3. Leakage          — 未来信息泄露
  4. Interpretability — 经济可解释性
  5. Safety           — 计算安全

用法:
    from src.quality import MultiAgentQualityChecker

    checker = MultiAgentQualityChecker()
    report = checker.check(l1_analysis_report)
    if not report.passed:
        for flag in report.blocking_flags:
            print(f"❌ {flag}")
"""

from .checker import MultiAgentQualityChecker
from .schema import (
    AgentRole,
    AgentVerdict,
    QualityReport,
    Severity,
)

__all__ = [
    "MultiAgentQualityChecker",
    "QualityReport",
    "AgentVerdict",
    "AgentRole",
    "Severity",
]
