# -*- coding: utf-8 -*-
"""定时任务数据类型。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class JobState(str, Enum):
    """任务状态枚举。"""

    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    COMPLETED = "completed"

    def __str__(self) -> str:
        return self.value


class Fulfillment(str, Enum):
    """任务履约模式。"""

    KEEP = "keep"  # 循环执行
    ONCE = "once"  # 执行一次后标记完成
    ASK = "ask"  # 执行前询问用户

    def __str__(self) -> str:
        return self.value


@dataclass
class CronJob:
    """定时任务定义。

    schedule_type:
      - "at":    时间点执行（一次性），schedule_value="2026-07-08 15:00"
      - "every": 间隔执行（毫秒），  schedule_value="3600000"
      - "cron":  cron 表达式，      schedule_value="0 9 * * 1-5"
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    enabled: bool = True
    schedule_type: str = "cron"  # "at" | "every" | "cron"
    schedule_value: str = "0 9 * * 1-5"
    payload: str = ""
    fulfillment: str = "keep"  # "keep" | "once" | "ask"
    state: str = JobState.ACTIVE

    # 活跃窗口 — 限定时间段执行
    active_window_start: Optional[str] = None  # "09:00"
    active_window_end: Optional[str] = None  # "15:00"
    active_days: Optional[list[int]] = None  # [0,1,2,3,4] 周一到周五

    # 错误阈值
    error_count: int = 0
    max_errors: int = 5

    # 时间戳（ISO 格式字符串，JSON 序列化友好）
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None


@dataclass
class JobResult:
    """任务执行结果。"""

    job_id: str
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0
