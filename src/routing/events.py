# -*- coding: utf-8 -*-
"""事件驱动管道事件类型 — 全链路各阶段的事件 DTO。

每个 StageEvent 子类携带 discriminator type: Literal[...]，
便于序列化/反序列化及模式匹配。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Union

from src.routing.orchestrator import OrchestratorResult


# ---------------------------------------------------------------------------
# 事件类型鉴别器常量
# ---------------------------------------------------------------------------
EVENT_STAGE_STARTED = "stage_started"
EVENT_STAGE_COMPLETED = "stage_completed"
EVENT_STAGE_ERROR = "stage_error"
EVENT_DATA_FETCH = "data_fetch"
EVENT_ANALYSIS = "analysis"
EVENT_PIPELINE_COMPLETED = "pipeline_completed"


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StageEvent:
    """事件基类 — 所有管道事件的公共字段。"""
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def discriminator(self) -> str:
        """返回子类的事件类型标识。"""
        return "unknown"

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 序列化的 dict。"""
        result = {"type": self.discriminator, "timestamp": self.timestamp.isoformat()}
        for f in self.__dataclass_fields__:
            if f == "timestamp":
                continue
            val = getattr(self, f)
            if hasattr(val, "to_dict"):
                result[f] = val.to_dict()
            elif isinstance(val, datetime):
                result[f] = val.isoformat()
            elif isinstance(val, (list, tuple)):
                result[f] = [v.to_dict() if hasattr(v, "to_dict") else v for v in val]
            else:
                result[f] = val
        return result


# ---------------------------------------------------------------------------
# 具体事件子类
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StageStartedEvent(StageEvent):
    """阶段开始事件 — 标志管道中某个阶段的启动。"""
    type: Literal["stage_started"] = "stage_started"
    stage_name: str = ""

    @property
    def discriminator(self) -> str:
        return self.type


@dataclass(frozen=True)
class StageCompletedEvent(StageEvent):
    """阶段完成事件 — 标志管道中某个阶段成功结束。"""
    type: Literal["stage_completed"] = "stage_completed"
    stage_name: str = ""
    result_summary: str = ""
    duration_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def discriminator(self) -> str:
        return self.type


@dataclass(frozen=True)
class StageErrorEvent(StageEvent):
    """阶段错误事件 — 管道中某个阶段抛出的异常或业务错误。"""
    type: Literal["stage_error"] = "stage_error"
    stage_name: str = ""
    error_message: str = ""

    @property
    def discriminator(self) -> str:
        return self.type


@dataclass(frozen=True)
class DataFetchEvent(StageEvent):
    """数据获取事件 — 从 Provider 获取指定字段的快照。"""
    type: Literal["data_fetch"] = "data_fetch"
    provider: str = ""
    field: str = ""
    success: bool = True
    data_freshness: str = ""  # ISO 格式的新鲜度描述，如 "5min" / "1h"

    @property
    def discriminator(self) -> str:
        return self.type


@dataclass(frozen=True)
class AnalysisEvent(StageEvent):
    """分析维度事件 — 管道中某个分析维度的评分快照。"""
    type: Literal["analysis"] = "analysis"
    dimension: str = ""          # 分析维度, 如 "value" / "quality" / "momentum"
    score: float = 0.0           # 评分 0-100
    confidence: float = 0.0      # 信心度 0.0-1.0
    key_findings: list[str] = field(default_factory=list)  # 关键发现摘要

    @property
    def discriminator(self) -> str:
        return self.type


@dataclass(frozen=True)
class PipelineCompletedEvent(StageEvent):
    """管道完成事件 — 全链路分析结束。"""
    type: Literal["pipeline_completed"] = "pipeline_completed"
    result: OrchestratorResult = field(default_factory=lambda: OrchestratorResult(symbol="", name=""))

    @property
    def discriminator(self) -> str:
        return self.type

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        # OrchestratorResult 用 symbol + passed 摘要简化
        r = self.result
        base["result"] = {
            "symbol": r.symbol,
            "name": r.name,
            "passed": r.passed,
            "gate_status": r.gate_status,
            "blocked_by": r.blocked_by,
            "warning_count": len(r.warnings),
            "data_gap_count": len(r.data_gaps),
        }
        return base


# ---------------------------------------------------------------------------
# Union 类型 — 接收方可做 exhaustiveness check
# ---------------------------------------------------------------------------
PipelineEvent = Union[
    StageStartedEvent,
    StageCompletedEvent,
    StageErrorEvent,
    DataFetchEvent,
    AnalysisEvent,
    PipelineCompletedEvent,
]
