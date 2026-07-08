# -*- coding: utf-8 -*-
"""5 层路由内核 + 事件驱动管道基础设施。"""

from .admission import AdmissionCheck, AdmissionResult
from .diagnosis import DiagnosisEngine, DiagnosisReport
from .verdict import VerdictEngine, Verdict
from .positioning import PositioningEngine, TradeSignal
from .risk_control import RiskControlEngine, RiskCheck
from .risk_state import RiskState  # Phase 8: 风控状态机
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
    "RiskState",  # Phase 8: 风控状态机
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
]

