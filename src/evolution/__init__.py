# -*- coding: utf-8 -*-
"""策略进化模块 — 论文驱动的策略进化与全生命周期管理。

核心组件:
  - PaperImporter: URL → 论文文本 → 分类(策略/架构)
  - StrategyExtractor: 策略论文 → 结构化策略定义
  - ArchitectureAnalyzer: 架构论文 → 系统改进提案
  - BacktestValidator: 回测门禁(可配置阈值)
  - LifecycleManager: 策略全生命周期状态机
  - TrialRunner: 模拟盘自动运行
  - TrialMonitor: 策略持续监控与降级
  - RollbackManager: 策略撤回与版本回退
  - ProposalManager: 改进提案审批工作流
  - PipelineComparator: 管道A/B对比验证
  - EvolutionConfigLoader: YAML配置加载
"""

from __future__ import annotations

from .architecture_analyzer import ArchitectureAnalyzer
from .backtest_validator import BacktestValidationResult, BacktestValidator
from .config import EvolutionConfigLoader
from .lifecycle import LifecycleManager
from .paper_importer import PaperImporter
from .pipeline_comparator import PipelineComparator, PipelineComparisonResult
from .proposal import ProposalManager
from .rollback import RollbackManager
from .schema import (
    BacktestThresholds,
    EvolutionConfig,
    ExtractedStrategy,
    ImprovementProposal,
    LifecycleState,
    MonitoringConfig,
    PaperType,
    ProposalStatus,
    RollbackRecord,
    StateTransition,
    StrategyLifecycle,
    StrategyPaper,
    TransitionRequest,
    TransitionResponse,
    TransitionResult,
    TrialMetrics,
    TrialThresholds,
)
from .strategy_extractor import StrategyExtractor
from .trial_monitor import MonitorAlert, TrialMonitor
from .trial_runner import TrialRunner

__all__ = [
    # ── Schema ──
    "LifecycleState",
    "PaperType",
    "ProposalStatus",
    "TransitionResult",
    "StrategyPaper",
    "ExtractedStrategy",
    "ImprovementProposal",
    "StrategyLifecycle",
    "StateTransition",
    "TransitionRequest",
    "TransitionResponse",
    "TrialMetrics",
    "BacktestThresholds",
    "TrialThresholds",
    "MonitoringConfig",
    "EvolutionConfig",
    "RollbackRecord",
    # ── Core ──
    "PaperImporter",
    "StrategyExtractor",
    "ArchitectureAnalyzer",
    "BacktestValidator",
    "BacktestValidationResult",
    "LifecycleManager",
    "TrialRunner",
    "TrialMonitor",
    "MonitorAlert",
    "RollbackManager",
    "ProposalManager",
    "PipelineComparator",
    "PipelineComparisonResult",
    "EvolutionConfigLoader",
]
