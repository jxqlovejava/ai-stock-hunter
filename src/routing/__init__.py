# -*- coding: utf-8 -*-
"""5 层路由内核。"""

from .admission import AdmissionCheck, AdmissionResult
from .diagnosis import DiagnosisEngine, DiagnosisReport
from .verdict import VerdictEngine, Verdict
from .positioning import PositioningEngine, TradeSignal
from .risk_control import RiskControlEngine, RiskCheck
from .orchestrator import Orchestrator

__all__ = [
    "Orchestrator",
    "AdmissionCheck", "AdmissionResult",
    "DiagnosisEngine", "DiagnosisReport",
    "VerdictEngine", "Verdict",
    "PositioningEngine", "TradeSignal",
    "RiskControlEngine", "RiskCheck",
    # -- 向后兼容 (deprecated) --
    "L0Gate", "SecurityPass",
    "L1Analyzer", "AnalysisReport",
    "L2Judge",
    "L3Trader",
    "L4RiskOfficer",
]

# 向后兼容模块级别名
from .admission import L0Gate, SecurityPass  # noqa: E402, F811
from .diagnosis import L1Analyzer, AnalysisReport  # noqa: E402, F811
from .verdict import L2Judge  # noqa: E402, F811
from .positioning import L3Trader  # noqa: E402, F811
from .risk_control import L4RiskOfficer  # noqa: E402, F811
