# -*- coding: utf-8 -*-
"""架构论文分析器 — 从架构/方法论论文生成系统改进提案。

输入: 分类为 ARCHITECTURE 的 StrategyPaper
输出: ImprovementProposal (含目标模块、预期变更、成功标准)

用法:
    analyzer = ArchitectureAnalyzer()
    proposal = analyzer.analyze(paper)
    print(proposal.target_modules, proposal.expected_changes)
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .schema import (
    ImprovementProposal,
    PaperType,
    ProposalStatus,
    StrategyPaper,
)

logger = logging.getLogger(__name__)

# 模块名称 → 关键词映射 (用于自动匹配受影响模块)
MODULE_KEYWORDS: dict[str, list[str]] = {
    "src/routing/orchestrator.py": ["pipeline", "orchestration", "编排", "管道", "workflow"],
    "src/routing/l1_analyze.py": ["analysis", "scoring", "评分", "分析维度", "fundamental"],
    "src/routing/l2_judge.py": ["judgment", "weight", "裁决", "权重", "decision fusion"],
    "src/routing/l3_trade.py": ["position sizing", "仓位", "position", "trade signal", "信号生成"],
    "src/routing/l4_risk.py": ["risk management", "风控", "risk model", "VaR", "drawdown control"],
    "src/data/aggregator.py": ["data source", "数据源", "aggregation", "聚合", "multi-source"],
    "src/data/factor_pipeline.py": ["factor pipeline", "因子管道", "feature engineering", "factor construction"],
    "src/backtest/engine.py": ["backtest", "回测", "simulation", "event-driven"],
    "src/doctrine/": ["guardrails", "rules", "军规", "约束", "rule engine"],
    "src/sentiment/": ["sentiment", "情绪", "market sentiment", "investor sentiment"],
    "src/game_theory/": ["game theory", "博弈", "crowding", "资金流", "capital flow"],
    "src/macro/": ["macro", "宏观", "monetary", "credit cycle", "regime"],
    "src/learner/": ["learning", "evolution", "进化", "feedback", "校准", "calibration"],
}


class ArchitectureAnalyzer:
    """从架构类论文中提取系统改进建议。

    用法:
        analyzer = ArchitectureAnalyzer()
        proposal = analyzer.analyze(paper)
        # 人工审核后实施
    """

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, paper: StrategyPaper) -> ImprovementProposal:
        """分析架构论文，生成改进提案。

        Args:
            paper: 已分类为 ARCHITECTURE 的 StrategyPaper

        Returns:
            ImprovementProposal
        """
        proposal = ImprovementProposal(
            paper_id=paper.id,
            title=f"改进: {paper.title[:80]}",
            source_citation=paper.source_citation,
            status=ProposalStatus.DRAFT,
        )

        text = f"{paper.title}\n{paper.abstract}\n{paper.full_text[:8000]}"

        # 匹配受影响模块
        proposal.target_modules = self._match_modules(text)

        # 提取预期变更
        proposal.expected_changes = self._extract_changes(text)

        # 提取成功标准
        proposal.success_criteria = self._extract_criteria(text)

        # 生成描述
        proposal.description = self._generate_description(proposal, text)

        # 记录状态
        proposal.status_history.append({
            "status": ProposalStatus.DRAFT.value,
            "note": "从论文自动生成",
            "timestamp": proposal.created_at,
        })

        logger.info(
            "架构分析: %s → %d 个目标模块",
            paper.title[:50], len(proposal.target_modules),
        )
        return proposal

    # ------------------------------------------------------------------
    # Internal — Module Matching
    # ------------------------------------------------------------------

    def _match_modules(self, text: str) -> list[str]:
        """基于关键词匹配受影响的系统模块。"""
        matched = []
        text_lower = text.lower()
        for module, keywords in MODULE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score >= 2:  # 至少 2 个关键词命中
                matched.append(module)
        return matched if matched else ["src/routing/orchestrator.py"]  # 默认影响主编排器

    # ------------------------------------------------------------------
    # Internal — Change Extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_changes(text: str) -> str:
        """提取论文建议的变更内容。"""
        patterns = [
            r"(?:propose|proposed|we propose|we introduce|we present)(.{50,500}?)(?:\.\s|$)",
            r"(?:建议|本文提出|我们提出|本文改进)(.{50,500}?)(?:[。.]|$)",
            r"(?:contribution|contributions|main contribution)(.{50,500}?)(?:\.\s|$)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                content = m.group(1).strip()
                if len(content) > 20:
                    return content[:500]
        # 回退: 摘要
        return "参见论文摘要了解变更详情"

    @staticmethod
    def _extract_criteria(text: str) -> str:
        """提取验证/成功标准。"""
        criteria_pats = [
            r"(?:evaluat|valid|benchmark|evaluation|验证|评估|基准).*?(.{30,200}?)(?:\.\s|$)",
        ]
        for pat in criteria_pats:
            matches = re.findall(pat, text, re.IGNORECASE)
            if matches:
                return "; ".join(m[:120] for m in matches[:3])
        return "回测对比旧管道 vs 新管道的 Sharpe/MaxDD/胜率"

    @staticmethod
    def _generate_description(proposal: ImprovementProposal, _text: str) -> str:
        """生成提案描述。"""
        parts = [
            f"论文: {proposal.source_citation}",
            f"影响模块: {', '.join(proposal.target_modules)}",
            f"预期变更: {proposal.expected_changes[:150]}...",
            f"验证标准: {proposal.success_criteria[:150]}...",
        ]
        return "\n".join(parts)
