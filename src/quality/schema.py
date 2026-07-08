# -*- coding: utf-8 -*-
"""质量审查 DTO — Multi-Agent Quality Checker 输出。

借鉴 CogAlpha 论文设计，适配本项目的 诊断报告审查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Severity(str, Enum):
    """审查严重级别。"""
    CRITICAL = "critical"    # 必须阻止（如未来信息泄露）
    HIGH = "high"            # 应该修复（如数据过期）
    MEDIUM = "medium"        # 建议修复（如内部不一致）
    LOW = "low"              # 提醒（如缺少经济解释）
    INFO = "info"            # 信息


class AgentRole(str, Enum):
    """审查 Agent 角色 — 对应 CogAlpha 的多 Agent 质量审查器。"""
    DATA_FRESHNESS = "data_freshness"        # 数据新鲜度审查
    DATA_PROVENANCE = "data_provenance"      # 数据溯源级别与性质审查
    CONSISTENCY = "consistency"               # 内部一致性审查
    LEAKAGE = "leakage"                       # 未来信息泄露审查
    INTERPRETABILITY = "interpretability"     # 经济可解释性审查
    SAFETY = "safety"                         # 计算安全检查


@dataclass
class AgentVerdict:
    """单个审查 Agent 的裁决。"""
    agent: AgentRole
    passed: bool
    score: float          # 0-100
    severity: Severity = Severity.INFO
    flags: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    details: str = ""


@dataclass
class QualityReport:
    """多 Agent 综合质量审查报告。

    用法:
        checker = MultiAgentQualityChecker()
        report = checker.check(analysis_report)
        if not report.passed:
            print(f"质量审查未通过: {report.blocking_flags}")
    """

    symbol: str
    passed: bool = True
    overall_score: float = 100.0     # 0-100
    verdicts: list[AgentVerdict] = field(default_factory=list)

    # 聚合
    blocking_flags: list[str] = field(default_factory=list)    # CRITICAL/HIGH 的 flag
    warnings: list[str] = field(default_factory=list)           # MEDIUM/LOW 的 flag
    suggestions: list[str] = field(default_factory=list)

    checked_at: datetime = field(default_factory=datetime.now)

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.verdicts if v.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for v in self.verdicts if v.severity == Severity.HIGH)

    @property
    def ok_count(self) -> int:
        return sum(1 for v in self.verdicts if v.passed)

    def summary(self) -> str:
        """人类可读的审查摘要。"""
        lines = [
            f"质量审查: {self.symbol} 评分 {self.overall_score:.0f}/100",
            f"  {'✅ 通过' if self.passed else '❌ 未通过'}"
            f"  CRITICAL={self.critical_count} HIGH={self.high_count} OK={self.ok_count}/{len(self.verdicts)}",
        ]
        for v in self.verdicts:
            icon = "✅" if v.passed else {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "⚪", "INFO": "ℹ️"}.get(v.severity.value, "❓")
            lines.append(f"  {icon} {v.agent.value}: {v.score:.0f}/100 — {v.details}")
            for flag in v.flags:
                lines.append(f"      ⚑ {flag}")
            for sug in v.suggestions:
                lines.append(f"      💡 {sug}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "passed": self.passed,
            "overall_score": self.overall_score,
            "blocking_flags": self.blocking_flags,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
            "checked_at": self.checked_at.isoformat(),
            "verdicts": [
                {
                    "agent": v.agent.value,
                    "passed": v.passed,
                    "score": v.score,
                    "severity": v.severity.value,
                    "flags": v.flags,
                    "suggestions": v.suggestions,
                    "details": v.details,
                }
                for v in self.verdicts
            ],
        }
