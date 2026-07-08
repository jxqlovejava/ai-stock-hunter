# -*- coding: utf-8 -*-
"""基本面深度研究 — 护城河/财务红旗/DCF估值/管理层/研报聚合。"""

from .dcf import DCFValuator
from .management import ManagementEvaluator
from .moat import MoatAnalyzer
from .red_flags import RedFlagDetector
from .report_aggregator import ReportAggregator
from .research import CompanyDeepResearcher
from .schema import (
    AnalystConsensus,
    CompanyDeepReport,
    DCFValuation,
    ManagementProfile,
    MoatProfile,
    MoatSource,
    MoatWidth,
    RedFlag,
    RedFlagReport,
    RedFlagSeverity,
)

__all__ = [
    # Schema
    "MoatWidth", "MoatSource", "MoatProfile",
    "RedFlagSeverity", "RedFlag", "RedFlagReport",
    "DCFValuation", "ManagementProfile",
    "AnalystConsensus", "CompanyDeepReport",
    # Analyzers
    "MoatAnalyzer", "RedFlagDetector", "DCFValuator",
    "ManagementEvaluator", "ReportAggregator",
    "CompanyDeepResearcher",
]
