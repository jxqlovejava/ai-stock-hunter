# -*- coding: utf-8 -*-
"""博弈论模块 — 统一导出。"""

from __future__ import annotations

from . import margin  # noqa: F401 — register MarginAnalyzer
from .comparative import MARKET_COMPARISONS, compare_markets, asymmetry_report
from .dominance import DominanceClassifier, DominanceProfile
from .fund_positioning import FundCrowdingSignal, FundPositioningAnalyzer
from .margin import MarginAnalyzer, MarginProfile
from .northbound import NorthboundAnalyzer, NorthboundProfile
from .players import PLAYER_PROFILES, PlayerProfile, PlayerType
from .playbooks import TOP_PLAYBOOKS, Playbook, get_playbook_evidence_summary
from .playbook_validator import (
    EvidenceGrade,
    PlaybookValidation,
    PlaybookValidator,
    SeatWinRate,
    ValidationReport,
    get_seat_rankings,
    upgrade_playbook_evidence,
    validate_playbooks,
)
from .price_impact import PRICE_IMPACT_PROFILES, PriceImpact
from .rules import (
    A_SHARE_RULES,
    TOP_3_RULES,
    EvidenceLevel,
    MarketRule,
    RuleCapitalFlowModel,
    RuleCategory,
)
from .seats import SeatActivity, SeatInfo, SeatTracker
from .manipulation import ManipulationDetector, ManipulationResult, ManipulationSignal


def get_game_theory_summary() -> str:
    """返回博弈论模块的知识概览。"""
    lines = [
        "# A 股博弈论知识库",
        "",
        f"## 规则库: {len(A_SHARE_RULES)} 条核心规则",
        f"## 核心玩家: {len(PLAYER_PROFILES)} 类",
        f"## 操盘手法: {len(TOP_PLAYBOOKS)} 种",
        f"## 价格冲击: {len(PRICE_IMPACT_PROFILES)} 类",
        f"## 跨市场对比: {len(MARKET_COMPARISONS)} 维度",
        f"## 资金流因果: {len(TOP_3_RULES)} 条",
        "",
        "## 规则类别分布",
    ]
    categories: dict[str, list[MarketRule]] = {}
    for r in A_SHARE_RULES:
        cat = r.category.value
        categories.setdefault(cat, []).append(r)
    for cat, rules in categories.items():
        names = "、".join(r.name for r in rules)
        lines.append(f"- {cat} ({len(rules)}): {names}")

    lines += [
        "",
        "## 证据等级分布",
        f"- VERIFIED: {sum(1 for r in A_SHARE_RULES if r.evidence == EvidenceLevel.VERIFIED)}",
        f"- HYPOTHESIS: {sum(1 for r in A_SHARE_RULES if r.evidence == EvidenceLevel.HYPOTHESIS)}",
        f"- HEURISTIC: {sum(1 for r in A_SHARE_RULES if r.evidence == EvidenceLevel.HEURISTIC)}",
    ]
    return "\n".join(lines)


__all__ = [
    # Rules
    "A_SHARE_RULES", "TOP_3_RULES", "MarketRule", "RuleCategory",
    "RuleCapitalFlowModel", "EvidenceLevel",
    # Players
    "PLAYER_PROFILES", "PlayerProfile", "PlayerType",
    # Analyzers
    "DominanceClassifier", "DominanceProfile",
    "FundCrowdingSignal", "FundPositioningAnalyzer",
    "MarginAnalyzer", "MarginProfile",
    "NorthboundAnalyzer", "NorthboundProfile",
    "SeatActivity", "SeatInfo", "SeatTracker",
    # Playbooks
    "TOP_PLAYBOOKS", "Playbook", "get_playbook_evidence_summary",
    # Playbook Validator (Phase 2)
    "PlaybookValidator", "PlaybookValidation", "SeatWinRate",
    "ValidationReport", "EvidenceGrade",
    "validate_playbooks", "get_seat_rankings", "upgrade_playbook_evidence",
    # Price Impact
    "PRICE_IMPACT_PROFILES", "PriceImpact",
    # Comparative
    "MARKET_COMPARISONS", "compare_markets", "asymmetry_report",
    # Manipulation Detection (Phase 10)
    "ManipulationDetector", "ManipulationResult", "ManipulationSignal",
    # Summary
    "get_game_theory_summary",
]
