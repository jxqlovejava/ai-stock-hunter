# -*- coding: utf-8 -*-
"""行业分析模块。

借鉴 cyberagent 物理瓶颈框架 + FinceptTerminal 行业数据模型
+ Serenity.skill 研究优先级 / 先层后票 workflow。
"""

from .bottleneck import BottleneckAnalysis, BottleneckType, SupplyChainLayer
from .classifier import SectorClassifier
from .competition import CompetitionAnalyzer
from .research import SectorResearchReporter
from .schema import (
    BarrierLevel,
    CompetitionProfile,
    SectorClass,
    SectorLevel,
    SectorReport,
    SectorValuation,
    StepStatus,
    SupplyChainNode as DeepSupplyChainNode,
    SupplyChainPosition,
    ValuationMethod,
)
from .serenity_scorecard import (
    SerenityScorecardResult,
    estimate_from_bottleneck_type,
    score_card,
    score_from_ratings,
    template_dict as serenity_scorecard_template,
)
from .serenity_workflow import (
    A_SHARE_EVIDENCE_CHECKLIST,
    A_SHARE_RED_FLAGS,
    CompanyResearchRank,
    LayerRanking,
    SerenityEvidenceStrength,
    SerenityRole,
    ThemeScanResult,
    format_challenge_block,
    format_theme_scan_report,
    validate_theme_scan_completeness,
)
from .supply_chain import SUPPLY_CHAINS, SupplyChainDeepMapper, classify_stock
from .valuation import SectorValuationFramework

__all__ = [
    # Legacy
    "BottleneckAnalysis", "BottleneckType", "SupplyChainLayer",
    "SUPPLY_CHAINS", "classify_stock",
    # New: Schema
    "SectorLevel", "SectorClass", "BarrierLevel", "CompetitionProfile",
    "ValuationMethod", "SectorValuation", "SupplyChainPosition",
    "DeepSupplyChainNode", "SectorReport", "StepStatus",
    # New: Engines
    "SectorClassifier", "CompetitionAnalyzer",
    "SectorValuationFramework", "SupplyChainDeepMapper",
    "SectorResearchReporter",
    # Serenity
    "SerenityScorecardResult", "score_card", "score_from_ratings",
    "estimate_from_bottleneck_type", "serenity_scorecard_template",
    "SerenityRole", "SerenityEvidenceStrength",
    "LayerRanking", "CompanyResearchRank", "ThemeScanResult",
    "A_SHARE_EVIDENCE_CHECKLIST", "A_SHARE_RED_FLAGS",
    "format_challenge_block", "format_theme_scan_report",
    "validate_theme_scan_completeness",
]
