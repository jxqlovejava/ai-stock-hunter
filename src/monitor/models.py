"""Monitor Event 数据模型 — 不可变事件类型.

Ref: ai-gold-miner events/models.py (CalendarEvent with MONITOR type).
Adapted for A-stock: margin balance, block trades, northbound, technical levels.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MonitorStatus(str, Enum):
    ACTIVE = "active"         # 观测中
    TRIGGERED = "triggered"   # 已触发
    EXPIRED = "expired"       # 已过期


class MonitorType(str, Enum):
    MARGIN = "margin"                     # 融资融券
    BLOCK_TRADE = "block_trade"           # 大宗交易
    NORTHBOUND = "northbound"             # 北向资金
    TECHNICAL = "technical"               # 技术面关键位
    SENTIMENT = "sentiment"               # 情绪极端
    PRICE_LEVEL = "price_level"           # 价格关键位
    DIVERGENCE_CONSENSUS = "divergence_consensus"  # 分歧/一致状态
    CUSTOM = "custom"                     # 自定义


@dataclass
class MonitorEvent:
    """持续观测事件.

    与 ai-gold-miner CalendarEvent (event_type=MONITOR) 对应。
    存储在 data/monitor_events.jsonl，JSONL 只追加 + 原地更新。
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""                                    # 事件名称
    monitor_type: MonitorType = MonitorType.CUSTOM    # 类型
    symbol: str = ""                                  # 相关股票代码
    symbol_name: str = ""                             # 股票名称

    # 观测配置
    status: MonitorStatus = MonitorStatus.ACTIVE
    trigger_condition: str = ""                       # 触发条件 (自然语言)
    check_frequency: str = "on_analysis"              # "on_analysis" | "daily"
    action_on_trigger: str = ""                       # 触发后建议动作

    # 时间
    created_at: str = ""                              # ISO 格式
    triggered_at: str = ""                            # 触发时间 ISO
    expires_at: str = ""                              # 过期时间 ISO

    # 触发结果
    trigger_result: str = ""                          # 触发时实际结果
    trigger_direction: str = "neutral"                # "bullish" / "bearish" / "neutral"
    trigger_severity: str = "medium"                  # "high" / "medium" / "info"

    # 溯源
    parent_analysis: str = ""                         # 创建此 monitor 的分析 session
    source_dimension: str = ""                        # 来源维度 (margin/technical/...)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_margin_alert(
        cls,
        code: str,
        name: str,
        alert_type: str,
        message: str,
        direction: str = "bearish",
        severity: str = "medium",
        trigger_condition: str = "",
        action: str = "",
        parent_analysis: str = "",
    ) -> "MonitorEvent":
        """从 MarginAlert 创建 MonitorEvent."""
        now = datetime.now()
        return cls(
            name=f"[{name}] {alert_type}",
            monitor_type=MonitorType.MARGIN,
            symbol=code,
            symbol_name=name,
            status=MonitorStatus.ACTIVE,
            trigger_condition=trigger_condition or message,
            check_frequency="on_analysis",
            action_on_trigger=action or "关注融资余额变化，评估是否需要调整仓位",
            created_at=now.isoformat(),
            trigger_direction=direction,
            trigger_severity=severity,
            parent_analysis=parent_analysis,
            source_dimension="margin",
            metadata={
                "alert_type": alert_type,
                "initial_message": message,
            },
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MonitorEvent":
        """从 JSONL 行反序列化."""
        return cls(
            event_id=d.get("event_id", ""),
            name=d.get("name", ""),
            monitor_type=MonitorType(d.get("monitor_type", "custom")),
            symbol=d.get("symbol", ""),
            symbol_name=d.get("symbol_name", ""),
            status=MonitorStatus(d.get("status", "active")),
            trigger_condition=d.get("trigger_condition", ""),
            check_frequency=d.get("check_frequency", "on_analysis"),
            action_on_trigger=d.get("action_on_trigger", ""),
            created_at=d.get("created_at", ""),
            triggered_at=d.get("triggered_at", ""),
            expires_at=d.get("expires_at", ""),
            trigger_result=d.get("trigger_result", ""),
            trigger_direction=d.get("trigger_direction", "neutral"),
            trigger_severity=d.get("trigger_severity", "medium"),
            parent_analysis=d.get("parent_analysis", ""),
            source_dimension=d.get("source_dimension", ""),
            metadata=d.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSONL 行."""
        return {
            "event_id": self.event_id,
            "name": self.name,
            "monitor_type": self.monitor_type.value,
            "symbol": self.symbol,
            "symbol_name": self.symbol_name,
            "status": self.status.value,
            "trigger_condition": self.trigger_condition,
            "check_frequency": self.check_frequency,
            "action_on_trigger": self.action_on_trigger,
            "created_at": self.created_at,
            "triggered_at": self.triggered_at,
            "expires_at": self.expires_at,
            "trigger_result": self.trigger_result,
            "trigger_direction": self.trigger_direction,
            "trigger_severity": self.trigger_severity,
            "parent_analysis": self.parent_analysis,
            "source_dimension": self.source_dimension,
            "metadata": self.metadata,
        }

    @property
    def is_active(self) -> bool:
        return self.status == MonitorStatus.ACTIVE

    @property
    def is_triggered(self) -> bool:
        return self.status == MonitorStatus.TRIGGERED

    @property
    def age_hours(self) -> float:
        """从创建到现在的小时数."""
        if not self.created_at:
            return 0
        try:
            created = datetime.fromisoformat(self.created_at)
            return (datetime.now() - created).total_seconds() / 3600
        except (ValueError, TypeError):
            return 0
