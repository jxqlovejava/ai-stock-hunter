# -*- coding: utf-8 -*-
"""统一护栏执行器 — 在每个管道阶段后强制执行数据质量和安全规则。

Phase 1: 护栏体系核心实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.data.source_citation import SourceCitation


@dataclass
class GuardrailViolation:
    """护栏违规记录。"""

    rule: str  # 违规规则名
    severity: str  # "FATAL" / "WARNING" / "INFO"
    message: str  # 人类可读描述
    stage: str = ""  # 违规发生的管道阶段, 如 "L1" / "L2"
    context: dict = field(default_factory=dict)  # 额外上下文


class GuardrailEnforcer:
    """管道护栏执行器。

    在 L0-L4 每个阶段后调用，检查数据质量和安全规则。
    """

    MIN_CONFIDENCE = 0.6  # 最低信心度阈值 — 低于此值禁止进入 L3
    MAX_UNSOURCED_RATIO = 0.3  # 分析报告中 [UNSOURCED] 数据点最大比例

    def enforce(
        self,
        stage: str,
        source_citations: list[SourceCitation] | None = None,
        confidence: float | None = None,
        data_freshness_check: bool = True,
        has_unsourced: bool = False,
        unsourced_count: int = 0,
        total_data_points: int = 0,
    ) -> list[GuardrailViolation]:
        """执行护栏检查。

        Args:
            stage: 管道阶段标识
            source_citations: 数据源引用列表
            confidence: 综合信心度
            data_freshness_check: 是否检查数据新鲜度
            has_unsourced: 是否有未标注来源的数据点
            unsourced_count: 未标注来源的数据点数量
            total_data_points: 总数据点数

        Returns:
            违规列表 (空列表 = 全部通过)
        """
        violations: list[GuardrailViolation] = []

        # 规则 1: 必须有数据来源
        if source_citations is not None and len(source_citations) == 0:
            violations.append(GuardrailViolation(
                rule="G001_NO_SOURCES",
                severity="WARNING",
                message="分析输出没有携带任何 source_citation",
                stage=stage,
            ))

        # 规则 2: 信心度检查
        if confidence is not None:
            if confidence < self.MIN_CONFIDENCE:
                violations.append(GuardrailViolation(
                    rule="G002_LOW_CONFIDENCE",
                    severity="FATAL" if stage in ("L2", "L3") else "WARNING",
                    message=f"信心度 {confidence:.2f} 低于阈值 {self.MIN_CONFIDENCE}",
                    stage=stage,
                    context={"confidence": confidence, "threshold": self.MIN_CONFIDENCE},
                ))
            elif confidence < 0.8:
                violations.append(GuardrailViolation(
                    rule="G003_MODERATE_CONFIDENCE",
                    severity="INFO",
                    message=f"信心度 {confidence:.2f} 中等, 建议标注风险",
                    stage=stage,
                    context={"confidence": confidence},
                ))

        # 规则 3: 数据新鲜度检查
        if data_freshness_check and source_citations:
            stale = [c for c in source_citations if not c.is_fresh]
            if stale:
                stale_fields = [f"{c.provider}:{c.field}" for c in stale]
                violations.append(GuardrailViolation(
                    rule="G004_STALE_DATA",
                    severity="WARNING",
                    message=f"以下数据已过期: {', '.join(stale_fields[:5])}",
                    stage=stage,
                    context={"stale_count": len(stale), "stale_fields": stale_fields[:5]},
                ))

        # 规则 4: 未标注来源比例
        if total_data_points > 0 and has_unsourced:
            ratio = unsourced_count / total_data_points
            if ratio > self.MAX_UNSOURCED_RATIO:
                violations.append(GuardrailViolation(
                    rule="G005_EXCESSIVE_UNSOURCED",
                    severity="WARNING",
                    message=f"未标注来源比例 {ratio:.0%} 超过上限 {self.MAX_UNSOURCED_RATIO:.0%}",
                    stage=stage,
                    context={"unsourced_count": unsourced_count, "total": total_data_points},
                ))
            elif unsourced_count > 0:
                violations.append(GuardrailViolation(
                    rule="G006_HAS_UNSOURCED",
                    severity="INFO",
                    message=f"{unsourced_count}/{total_data_points} 个数据点未标注来源, 已标记 [UNSOURCED]",
                    stage=stage,
                ))

        return violations

    def is_blocked(self, violations: list[GuardrailViolation]) -> bool:
        """是否有 FATAL 级别违规阻止管道继续。"""
        return any(v.severity == "FATAL" for v in violations)

    def get_warnings(self, violations: list[GuardrailViolation]) -> list[str]:
        """提取所有 WARNING 级别消息。"""
        return [v.message for v in violations if v.severity == "WARNING"]
