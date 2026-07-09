# -*- coding: utf-8 -*-
"""行业研究 Workflow 验证器。

确保 6+1 步行业研究框架的步骤完整性和数据质量。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.industry.schema import SectorReport, StepStatus


# ---------------------------------------------------------------------------
# Step definitions
# ---------------------------------------------------------------------------

@dataclass
class WorkflowStep:
    step_id: str
    name: str
    description: str


BASE_STEPS: list[WorkflowStep] = [
    WorkflowStep("step1", "行业定位", "申万分类 + 东财板块归属 + 生命周期判定"),
    WorkflowStep("step2", "市场规模", "TAM / CAGR / CR5 / 集中度趋势"),
    WorkflowStep("step3", "竞争格局", "波特五力 / 护城河 / 份额变化 / 新进入者"),
    WorkflowStep("step4", "估值背景", "PE/PB 历史分位 + 拥挤度 + 北向配置"),
    WorkflowStep("step5", "催化剂", "政策事件 / 技术突破 / M&A / 行业日历"),
    WorkflowStep("step6", "供应链瓶颈", "供应链映射 / 瓶颈身份 / 成本传导 / 定价位置"),
]

GLOBAL_STEP = WorkflowStep(
    "step7", "全球供需平衡",
    "海外矿山产能 / 龙头对标 / 成本曲线 / 地缘风险 / 需求端拆解",
)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class SectorWorkflowValidator:
    """行业研究 Workflow 验证器。

    职责:
      1. 记录每个步骤的执行状态和数据质量
      2. 在报告返回前验证步骤完整性
      3. 生成 human-readable checklist

    strict=True  → 缺失步骤写入 data_gaps，降低 confidence
    strict=False → 只 warn，不 block
    """

    def mark_step(
        self,
        report: SectorReport,
        step_id: str,
        name: str,
        source_tier: str = "T2",
        freshness_hours: int = 24,
        confidence: float = 0.70,
        error: str = "",
    ) -> StepStatus:
        """标记一个步骤为已完成，同时标注数据质量。"""
        status = StepStatus(
            step_id=step_id,
            name=name,
            completed=True,
            confidence=confidence,
            source_tier=source_tier,
            freshness_hours=freshness_hours,
            error=error,
        )
        report.step_status[step_id] = status
        return status

    def mark_skipped(
        self,
        report: SectorReport,
        step_id: str,
        name: str,
        reason: str,
    ) -> StepStatus:
        """标记一个步骤被跳过（如 Step 7 对非全球大宗行业）。"""
        status = StepStatus(
            step_id=step_id,
            name=name,
            completed=False,
            confidence=0.0,
            source_tier="",
            freshness_hours=0,
            error=reason,
        )
        report.step_status[step_id] = status
        return status

    def validate(
        self,
        report: SectorReport,
        is_global: bool = False,
        strict: bool = True,
    ) -> tuple[bool, list[str]]:
        """验证步骤完整性。

        Args:
            report: 行业报告
            is_global: 是否全球定价大宗商品行业
            strict: True=缺失步骤写入 data_gaps; False=只 warn

        Returns:
            (passed, missing_step_names)
        """
        expected = list(BASE_STEPS)
        if is_global:
            expected.append(GLOBAL_STEP)

        missing: list[str] = []
        for step in expected:
            status = report.step_status.get(step.step_id)
            if status is None or not status.completed:
                missing.append(step.name)

        if missing and strict:
            for name in missing:
                report.data_gaps.append(f"[WORKFLOW_GAP] 步骤未完成: {name}")
            # 每缺失一步，confidence 降 0.05
            penalty = min(len(missing) * 0.05, 0.30)
            report.confidence = max(0.30, report.confidence - penalty)

        return len(missing) == 0, missing

    def format_checklist(self, report: SectorReport, is_global: bool = False) -> str:
        """生成结构化 checklist 文本，供 AI 输出或 CLI 展示。"""
        lines = ["📋 Workflow 执行清单:"]
        expected = list(BASE_STEPS)
        if is_global:
            expected.append(GLOBAL_STEP)

        for step in expected:
            status = report.step_status.get(step.step_id)
            if status and status.completed:
                icon = "✅"
                detail = f"tier={status.source_tier} conf={status.confidence:.2f} {status.freshness_hours}h"
            else:
                icon = "❌"
                detail = status.error if status else "未执行"

            lines.append(f"  {icon} {step.name} — {detail}")

        lines.append(f"\n  综合置信度: {report.confidence:.2f}")
        if report.data_gaps:
            lines.append(f"  数据缺口: {len(report.data_gaps)} 项")
        return "\n".join(lines)

    def validate_dict(
        self,
        data: dict,
        is_global: bool = False,
        strict: bool = True,
    ) -> tuple[bool, list[str]]:
        """对 orchestrator 返回的 dict 做验证 (而非 SectorReport)。

        检查 dict 中是否有关键子 dict/字段。
        """
        # 定义 dict 中每步对应的 key 检查
        step_keys = {
            "step1": ["sector_name"],                                              # 行业定位
            "step2": ["tam_estimate", "sector_name"],                              # 市场规模
            "step3": ["competition"],                                              # 竞争格局
            "step4": ["valuation"],                                                # 估值背景
            "step5": ["catalysts", "catalyst_score"],                              # 催化剂 (暂不强制)
            "step6": ["supply_chain"],                                             # 供应链瓶颈
        }
        if is_global:
            step_keys["step7"] = ["global_commodity"]                              # 全球供需

        name_map = {s.step_id: s.name for s in BASE_STEPS}
        name_map["step7"] = GLOBAL_STEP.name

        missing: list[str] = []
        for step_id, keys in step_keys.items():
            if step_id in ("step2", "step5"):
                # Step 2 和 Step 5 可选，不强制
                continue
            found = any(k in data for k in keys)
            if not found:
                missing.append(name_map.get(step_id, step_id))

        if missing and strict:
            data.setdefault("data_gaps", [])
            for name in missing:
                data["data_gaps"].append(f"[WORKFLOW_GAP] 步骤未完成: {name}")
            data["confidence"] = max(0.30, data.get("confidence", 0.70) - len(missing) * 0.05)

        return len(missing) == 0, missing
