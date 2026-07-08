# -*- coding: utf-8 -*-
"""5 层路由内核 + 事件驱动管道基础设施。"""

from .admission import AdmissionCheck, AdmissionResult
from .diagnosis import DiagnosisEngine, DiagnosisReport
from .verdict import VerdictEngine, Verdict
from .positioning import PositioningEngine, TradeSignal
from .risk_control import RiskControlEngine, RiskCheck
from .orchestrator import Orchestrator
from .signal import (
    Direction,
    PortfolioTarget,
    Signal,
    SignalScore,
    SignalTracker,
    signal_from_verdict,
    target_from_signal,
)
from .events import (
    StageEvent,
    StageStartedEvent,
    StageCompletedEvent,
    StageErrorEvent,
    DataFetchEvent,
    AnalysisEvent,
    PipelineCompletedEvent,
    PipelineEvent,
    EVENT_STAGE_STARTED,
    EVENT_STAGE_COMPLETED,
    EVENT_STAGE_ERROR,
    EVENT_DATA_FETCH,
    EVENT_ANALYSIS,
    EVENT_PIPELINE_COMPLETED,
)
from .scratchpad import AnalysisScratchpad
from .context import AnalysisContext, TokenCounter, create_context

__all__ = [
    "Orchestrator",
    "AdmissionCheck", "AdmissionResult",
    "DiagnosisEngine", "DiagnosisReport",
    "VerdictEngine", "Verdict",
    "PositioningEngine", "TradeSignal",
    "RiskControlEngine", "RiskCheck",
    # -- Signal + PortfolioTarget (LEAN Insight pattern) --
    "Direction",
    "Signal",
    "SignalScore",
    "SignalTracker",
    "PortfolioTarget",
    "signal_from_verdict",
    "target_from_signal",
    # -- 事件驱动管道 --
    "StageEvent",
    "StageStartedEvent",
    "StageCompletedEvent",
    "StageErrorEvent",
    "DataFetchEvent",
    "AnalysisEvent",
    "PipelineCompletedEvent",
    "PipelineEvent",
    "EVENT_STAGE_STARTED",
    "EVENT_STAGE_COMPLETED",
    "EVENT_STAGE_ERROR",
    "EVENT_DATA_FETCH",
    "EVENT_ANALYSIS",
    "EVENT_PIPELINE_COMPLETED",
    "AnalysisScratchpad",
    "AnalysisContext",
    "TokenCounter",
    "create_context",
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
