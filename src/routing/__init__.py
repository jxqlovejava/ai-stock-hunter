# -*- coding: utf-8 -*-
"""5 层路由内核 + 事件驱动管道基础设施。"""

from .admission import AdmissionCheck, AdmissionResult
from .alert_engine import (
    ALERT_PRIORITY_MAP,
    AlertCheckResult,
    AlertEngine,
    AlertPriority,
    AlertType,
    PriceAlert,
    get_alert_summary,
)
from .diagnosis import DiagnosisEngine, DiagnosisReport
from .verdict import VerdictEngine, Verdict
from .positioning import PositioningEngine, TradeSignal
from .risk_control import RiskControlEngine, RiskCheck
from .risk_state import RiskState  # Phase 8: 风控状态机
from .position_monitor import PositionMonitor, PositionSnapshot, MonitorResult  # Phase 11
from .position_state import (  # Phase 12: 实时持仓 HWM + 动态止盈止损
    PositionState,
    PositionStateManager,
    DynamicStopCalculator,
    StopAlert,
    StopStage,
    AlertType,
)
from .orchestrator import Orchestrator
from .fundamental_diagnosis import (
    FundamentalDiagnosisEngine,
    FundamentalDiagnosisReport,
    Q1Answer,
    Q2Answer,
    Q3Answer,
)
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
    # -- Price Alert Engine --
    "AlertEngine", "PriceAlert", "AlertType", "AlertPriority",
    "AlertCheckResult", "get_alert_summary", "ALERT_PRIORITY_MAP",
    "DiagnosisEngine", "DiagnosisReport",
    "VerdictEngine", "Verdict",
    "PositioningEngine", "TradeSignal",
    "RiskControlEngine", "RiskCheck",
    "RiskState",  # Phase 8: 风控状态机
    "PositionMonitor", "PositionSnapshot", "MonitorResult",  # Phase 11
    # -- Phase 12: 实时持仓 HWM + 动态止盈止损 --
    "PositionState", "PositionStateManager", "DynamicStopCalculator",
    "StopAlert", "StopStage", "AlertType",
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
    # -- 三大根本问题诊断 --
    "FundamentalDiagnosisEngine",
    "FundamentalDiagnosisReport",
    "Q1Answer",
    "Q2Answer",
    "Q3Answer",
]

