# -*- coding: utf-8 -*-
"""策略进化模块 — 数据类型定义 (DTO-first)。

所有跨模块数据使用 @dataclass，不用裸 dict。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


# ------------------------------------------------------------------
# Enums
# ------------------------------------------------------------------

class LifecycleState(Enum):
    """策略生命周期状态。"""
    EXTRACTED = "extracted"        # 论文已解析，待回测
    CANDIDATE = "candidate"        # 回测通过，候选池
    TRIAL = "trial"                # 模拟盘运行中
    ACTIVE = "active"              # 实战中
    DEGRADED = "degraded"          # 表现不佳
    OPTIMIZING = "optimizing"      # 自动优化中
    REJECTED = "rejected"          # 未通过
    RETIRED = "retired"            # 已退役
    ERROR = "error"                # 异常


class PaperType(Enum):
    """论文类型。"""
    STRATEGY = "strategy"          # 策略类 — 因子/择时/选股
    ARCHITECTURE = "architecture"  # 架构类 — 管道/方法论/框架
    UNKNOWN = "unknown"            # 无法分类


class ProposalStatus(Enum):
    """改进提案状态。"""
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTING = "implementing"
    VALIDATING = "validating"
    MERGED = "merged"
    CLOSED = "closed"


class TransitionResult(Enum):
    """状态转换结果。"""
    OK = "ok"
    INVALID_TRANSITION = "invalid_transition"
    CONDITION_NOT_MET = "condition_not_met"
    ERROR = "error"


# ------------------------------------------------------------------
# State Machine — Transition Map
# ------------------------------------------------------------------

# 每个状态允许跳转到哪些状态
STATE_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.EXTRACTED:  {LifecycleState.CANDIDATE, LifecycleState.REJECTED, LifecycleState.ERROR},
    LifecycleState.CANDIDATE:  {LifecycleState.TRIAL, LifecycleState.REJECTED, LifecycleState.EXTRACTED},
    LifecycleState.TRIAL:      {LifecycleState.ACTIVE, LifecycleState.DEGRADED, LifecycleState.CANDIDATE},
    LifecycleState.ACTIVE:     {LifecycleState.DEGRADED, LifecycleState.RETIRED},
    LifecycleState.DEGRADED:   {LifecycleState.OPTIMIZING, LifecycleState.TRIAL, LifecycleState.RETIRED},
    LifecycleState.OPTIMIZING: {LifecycleState.CANDIDATE},
    LifecycleState.REJECTED:   {LifecycleState.EXTRACTED, LifecycleState.RETIRED},
    LifecycleState.RETIRED:    set(),
    LifecycleState.ERROR:      {LifecycleState.EXTRACTED, LifecycleState.RETIRED},
}


# ------------------------------------------------------------------
# Config DTOs
# ------------------------------------------------------------------

@dataclass
class BacktestThresholds:
    """回测通过条件 — 可配置。"""
    min_sharpe_ratio: float = 0.5
    min_total_return: float = 0.10
    max_max_drawdown: float = 0.25
    min_trades: int = 20
    benchmark: str = "000300.SH"  # 沪深300

    @classmethod
    def from_dict(cls, d: dict) -> "BacktestThresholds":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class TrialThresholds:
    """模拟盘通过条件 — 可配置。"""
    min_duration_days: int = 30
    min_trades: int = 10
    sharpe_superiority: float = 0.10   # 需超基准 Sharpe 0.10
    max_drawdown_limit: float = 0.20
    benchmark: str = "000300.SH"

    @classmethod
    def from_dict(cls, d: dict) -> "TrialThresholds":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MonitoringConfig:
    """策略监控配置。"""
    check_interval_hours: int = 24
    degradation_window_days: int = 14  # 连续N天低阈值触发 DEGRADED
    auto_optimize_on_degrade: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "MonitoringConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class EvolutionConfig:
    """进化模块总配置。"""
    backtest: BacktestThresholds = field(default_factory=BacktestThresholds)
    trial: TrialThresholds = field(default_factory=TrialThresholds)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)

    @classmethod
    def from_dict(cls, d: dict) -> "EvolutionConfig":
        return cls(
            backtest=BacktestThresholds.from_dict(d.get("backtest", {})),
            trial=TrialThresholds.from_dict(d.get("trial", {})),
            monitoring=MonitoringConfig.from_dict(d.get("monitoring", {})),
        )


# ------------------------------------------------------------------
# Paper DTOs
# ------------------------------------------------------------------

@dataclass
class StrategyPaper:
    """一篇论文的解析结果。"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    url: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    full_text: str = ""
    paper_type: PaperType = PaperType.UNKNOWN
    classification_confidence: float = 0.0

    # 提取结果
    extracted_strategy: Optional[ExtractedStrategy] = None
    extracted_proposal: Optional[ImprovementProposal] = None

    # 元数据
    source_citation: str = ""       # 论文出处引用
    imported_at: str = field(default_factory=lambda: datetime.now().isoformat())
    notes: str = ""                 # 用户备注


@dataclass
class ExtractedStrategy:
    """从论文中提取的策略定义。"""
    paper_id: str = ""
    strategy_name: str = ""
    description: str = ""
    strategy_type: str = ""          # "factor" | "timing" | "screening" | "risk" | "composite"

    # 策略逻辑
    entry_conditions: list[str] = field(default_factory=list)  # 买入条件 (自然语言)
    exit_conditions: list[str] = field(default_factory=list)   # 卖出条件
    parameters: dict[str, Any] = field(default_factory=dict)   # 参数

    # 来源标记
    sourced_fields: list[str] = field(default_factory=list)    # 有论文依据的字段
    unsourced_fields: list[str] = field(default_factory=list)  # [UNSOURCED] 字段
    extraction_confidence: float = 0.0

    # 原始引用
    paper_sections: list[str] = field(default_factory=list)    # 策略逻辑对应的论文章节


# ------------------------------------------------------------------
# Lifecycle DTOs
# ------------------------------------------------------------------

@dataclass
class StrategyLifecycle:
    """策略生命周期实体 — 持久化到策略注册表。"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    paper_id: str = ""
    strategy_name: str = ""
    strategy_version: str = ""       # 对应 StrategyRegistry 中的版本

    state: LifecycleState = LifecycleState.EXTRACTED
    state_history: list[StateTransition] = field(default_factory=list)

    # 回测结果
    backtest_sharpe: Optional[float] = None
    backtest_return: Optional[float] = None
    backtest_max_dd: Optional[float] = None
    backtest_passed: bool = False
    backtest_run_at: Optional[str] = None

    # 模拟盘结果
    trial_started_at: Optional[str] = None
    trial_ended_at: Optional[str] = None
    trial_sharpe: Optional[float] = None
    trial_return: Optional[float] = None
    trial_max_dd: Optional[float] = None
    trial_trades: int = 0
    trial_passed: bool = False

    # 实战结果
    active_started_at: Optional[str] = None
    live_sharpe: Optional[float] = None
    live_return: Optional[float] = None
    live_max_dd: Optional[float] = None

    # 元数据
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    error_message: str = ""
    notes: str = ""


@dataclass
class StateTransition:
    """一次状态转换记录。"""
    from_state: LifecycleState
    to_state: LifecycleState
    reason: str = ""
    triggered_by: str = ""  # "auto" | "user" | "monitor"
    metrics_snapshot: dict[str, float] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TransitionRequest:
    """状态转换请求。"""
    lifecycle_id: str
    target_state: LifecycleState
    reason: str = ""
    triggered_by: str = "user"
    force: bool = False  # 跳过条件检查


@dataclass
class TransitionResponse:
    """状态转换响应。"""
    request: TransitionRequest
    result: TransitionResult = TransitionResult.OK
    message: str = ""
    new_state: Optional[LifecycleState] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ------------------------------------------------------------------
# Trial DTOs
# ------------------------------------------------------------------

@dataclass
class TrialMetrics:
    """模拟盘实时指标。"""
    lifecycle_id: str = ""
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    running_days: int = 0
    annualized_return: float = 0.0
    benchmark_return: float = 0.0
    excess_return: float = 0.0  # 超额收益
    calculated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ------------------------------------------------------------------
# Proposal DTOs
# ------------------------------------------------------------------

@dataclass
class ImprovementProposal:
    """系统改进提案 — 从架构论文生成。"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    paper_id: str = ""
    title: str = ""
    description: str = ""

    # 改动目标
    target_modules: list[str] = field(default_factory=list)   # 要改的模块
    expected_changes: str = ""                                  # 预期变更描述
    success_criteria: str = ""                                  # 成功标准

    status: ProposalStatus = ProposalStatus.DRAFT
    status_history: list[dict] = field(default_factory=list)

    # 验证
    pipeline_before_metrics: dict[str, float] = field(default_factory=dict)
    pipeline_after_metrics: dict[str, float] = field(default_factory=dict)
    improvement_pct: float = 0.0   # 改善幅度

    # 元数据
    source_citation: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    review_notes: str = ""
    implementation_notes: str = ""


# ------------------------------------------------------------------
# Rollback DTOs
# ------------------------------------------------------------------

@dataclass
class RollbackRecord:
    """策略撤回记录。"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    lifecycle_id: str = ""
    from_version: str = ""           # 撤回前版本
    to_version: str = ""             # 回退到版本
    reason: str = ""
    metrics_before_rollback: dict[str, float] = field(default_factory=dict)
    rolled_back_at: str = field(default_factory=lambda: datetime.now().isoformat())
