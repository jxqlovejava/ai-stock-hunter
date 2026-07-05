# -*- coding: utf-8 -*-
"""改进提案管理器 — 审批工作流 + 状态管理。

管理架构论文生成的公司提案的完整生命周期:
  DRAFT → PENDING_REVIEW → APPROVED/REJECTED → IMPLEMENTING → VALIDATING → MERGED

用法:
    mgr = ProposalManager()
    mgr.submit_for_review(proposal_id)
    mgr.approve(proposal_id, "方案合理，同意实施")
    mgr.mark_implementing(proposal_id)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from .schema import ImprovementProposal, ProposalStatus

logger = logging.getLogger(__name__)


class ProposalManager:
    """改进提案管理器。

    管理提案审批流程和状态转换。

    用法:
        mgr = ProposalManager("data/evolution_proposals.json")
        proposal = mgr.create(paper_id="p1", title="改进L1评分")
        mgr.submit_for_review(proposal.id)
    """

    VALID_TRANSITIONS: dict[ProposalStatus, set[ProposalStatus]] = {
        ProposalStatus.DRAFT: {ProposalStatus.PENDING_REVIEW, ProposalStatus.CLOSED},
        ProposalStatus.PENDING_REVIEW: {ProposalStatus.APPROVED, ProposalStatus.REJECTED},
        ProposalStatus.APPROVED: {ProposalStatus.IMPLEMENTING, ProposalStatus.CLOSED},
        ProposalStatus.REJECTED: {ProposalStatus.DRAFT, ProposalStatus.CLOSED},
        ProposalStatus.IMPLEMENTING: {ProposalStatus.VALIDATING, ProposalStatus.APPROVED},
        ProposalStatus.VALIDATING: {ProposalStatus.MERGED, ProposalStatus.IMPLEMENTING},
        ProposalStatus.MERGED: {ProposalStatus.CLOSED},
        ProposalStatus.CLOSED: set(),
    }

    def __init__(self, db_path: str = "data/evolution_proposals.json"):
        self._path = db_path
        self._proposals: dict[str, ImprovementProposal] = {}
        self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        paper_id: str = "",
        title: str = "",
        description: str = "",
        target_modules: Optional[list[str]] = None,
    ) -> ImprovementProposal:
        """创建新提案。"""
        proposal = ImprovementProposal(
            paper_id=paper_id,
            title=title,
            description=description,
            target_modules=target_modules or [],
            status=ProposalStatus.DRAFT,
        )
        proposal.status_history.append({
            "status": ProposalStatus.DRAFT.value,
            "note": "创建提案",
            "timestamp": datetime.now().isoformat(),
        })
        self._proposals[proposal.id] = proposal
        self._save()
        logger.info("提案创建: %s", title)
        return proposal

    def get(self, proposal_id: str) -> Optional[ImprovementProposal]:
        return self._proposals.get(proposal_id)

    def list_all(self) -> list[ImprovementProposal]:
        return list(self._proposals.values())

    def list_by_status(self, status: ProposalStatus) -> list[ImprovementProposal]:
        return [p for p in self._proposals.values() if p.status == status]

    def list_pending(self) -> list[ImprovementProposal]:
        """列出待审核提案。"""
        return self.list_by_status(ProposalStatus.PENDING_REVIEW)

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def submit_for_review(self, proposal_id: str) -> bool:
        """提交审核。"""
        return self._change_status(
            proposal_id, ProposalStatus.PENDING_REVIEW, "提交审核"
        )

    def approve(self, proposal_id: str, notes: str = "") -> bool:
        """审批通过。"""
        proposal = self.get(proposal_id)
        if proposal:
            proposal.review_notes = notes
        return self._change_status(
            proposal_id, ProposalStatus.APPROVED, f"审批通过: {notes}"
        )

    def reject(self, proposal_id: str, reason: str = "") -> bool:
        """驳回提案。"""
        proposal = self.get(proposal_id)
        if proposal:
            proposal.review_notes = reason
        return self._change_status(
            proposal_id, ProposalStatus.REJECTED, f"驳回: {reason}"
        )

    def mark_implementing(self, proposal_id: str) -> bool:
        """标记为实施中。"""
        return self._change_status(
            proposal_id, ProposalStatus.IMPLEMENTING, "开始实施"
        )

    def mark_validating(self, proposal_id: str) -> bool:
        """标记为验证中。"""
        return self._change_status(
            proposal_id, ProposalStatus.VALIDATING, "开始A/B验证"
        )

    def mark_merged(self, proposal_id: str, improvement_pct: float = 0.0) -> bool:
        """标记为已合入。"""
        proposal = self.get(proposal_id)
        if proposal:
            proposal.improvement_pct = improvement_pct
        return self._change_status(
            proposal_id, ProposalStatus.MERGED,
            f"合入主管道 (改善 {improvement_pct:+.1f}%)"
        )

    def close(self, proposal_id: str, reason: str = "") -> bool:
        """关闭提案。"""
        return self._change_status(
            proposal_id, ProposalStatus.CLOSED, f"关闭: {reason}"
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def set_pipeline_metrics(
        self,
        proposal_id: str,
        before: dict[str, float],
        after: dict[str, float],
    ):
        """设置管道对比指标。"""
        proposal = self.get(proposal_id)
        if proposal:
            proposal.pipeline_before_metrics = before
            proposal.pipeline_after_metrics = after
            if before:
                old_sharpe = before.get("sharpe_ratio", 0) or 0.001
                new_sharpe = after.get("sharpe_ratio", 0)
                proposal.improvement_pct = ((new_sharpe / old_sharpe) - 1) * 100
            self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _change_status(
        self, proposal_id: str, new_status: ProposalStatus, note: str
    ) -> bool:
        proposal = self.get(proposal_id)
        if proposal is None:
            logger.error("提案不存在: %s", proposal_id)
            return False

        allowed = self.VALID_TRANSITIONS.get(proposal.status, set())
        if new_status not in allowed and proposal.status != new_status:
            logger.warning(
                "不允许转换: %s → %s (允许: %s)",
                proposal.status.value, new_status.value,
                [s.value for s in allowed],
            )
            return False

        proposal.status = new_status
        proposal.status_history.append({
            "status": new_status.value,
            "note": note,
            "timestamp": datetime.now().isoformat(),
        })
        self._save()
        logger.info("提案 %s: %s", proposal_id, note)
        return True

    def _save(self):
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        data = {}
        for pid, p in self._proposals.items():
            data[pid] = {
                "id": p.id,
                "paper_id": p.paper_id,
                "title": p.title,
                "description": p.description,
                "target_modules": p.target_modules,
                "expected_changes": p.expected_changes,
                "success_criteria": p.success_criteria,
                "status": p.status.value,
                "status_history": p.status_history,
                "pipeline_before_metrics": p.pipeline_before_metrics,
                "pipeline_after_metrics": p.pipeline_after_metrics,
                "improvement_pct": p.improvement_pct,
                "source_citation": p.source_citation,
                "created_at": p.created_at,
                "review_notes": p.review_notes,
                "implementation_notes": p.implementation_notes,
            }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for pid, raw in data.items():
            self._proposals[pid] = ImprovementProposal(
                id=raw.get("id", pid),
                paper_id=raw.get("paper_id", ""),
                title=raw.get("title", ""),
                description=raw.get("description", ""),
                target_modules=raw.get("target_modules", []),
                expected_changes=raw.get("expected_changes", ""),
                success_criteria=raw.get("success_criteria", ""),
                status=ProposalStatus(raw.get("status", "draft")),
                status_history=raw.get("status_history", []),
                pipeline_before_metrics=raw.get("pipeline_before_metrics", {}),
                pipeline_after_metrics=raw.get("pipeline_after_metrics", {}),
                improvement_pct=raw.get("improvement_pct", 0.0),
                source_citation=raw.get("source_citation", ""),
                created_at=raw.get("created_at", ""),
                review_notes=raw.get("review_notes", ""),
                implementation_notes=raw.get("implementation_notes", ""),
            )
