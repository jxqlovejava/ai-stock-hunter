"""MonitorStore — JSONL 只追加 Monitor Event 存储.

Ref: ai-gold-miner events/store.py (EventStore JSONL pattern).
Adapted for A-stock monitor events.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import MonitorEvent, MonitorStatus

logger = logging.getLogger(__name__)


# 项目根目录下的 monitor 数据文件
_MONITOR_PATH = Path(__file__).parents[2] / "data" / "monitor_events.jsonl"


class MonitorStore:
    """Monitor Event JSONL 存储.

    - 只追加 (append)，不删除。
    - 状态变更通过 _rewrite_jsonl() 原地更新已有行。
    - 查询方法返回 active / triggered / all events。
    """

    def __init__(self, data_path: Path | None = None) -> None:
        self._data_path = data_path or _MONITOR_PATH
        self._data_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def append(self, event: MonitorEvent) -> MonitorEvent:
        """追加一条 monitor 事件."""
        _append_jsonl(self._data_path, event.to_dict())
        logger.debug(f"MonitorEvent 已记录: {event.name} (id={event.event_id[:8]}...)")
        return event

    # ------------------------------------------------------------------
    # 状态变更
    # ------------------------------------------------------------------

    def close_monitor(
        self,
        event_id: str,
        result: str,
        direction: str = "neutral",
        severity: str = "medium",
        new_status: str = "triggered",
    ) -> bool:
        """关闭 monitor: 记录触发结果.

        Args:
            event_id: 事件 ID (精确匹配)
            result: 触发时的实际结果描述
            direction: bullish / bearish / neutral
            severity: high / medium / info
            new_status: triggered 或 expired

        Returns:
            True if 找到并更新
        """
        events = self.load_all()
        updated = False
        now_iso = datetime.now().isoformat()

        for e in events:
            if e.event_id == event_id and e.status == MonitorStatus.ACTIVE:
                e.status = MonitorStatus(new_status)
                e.trigger_result = result
                e.trigger_direction = direction
                e.trigger_severity = severity
                e.triggered_at = now_iso
                updated = True
                break

        if updated:
            _rewrite_jsonl(self._data_path, events)
            logger.info(f"MonitorEvent 已关闭: {event_id[:8]}... → {new_status}")
        return updated

    def expire_monitor(self, event_id: str, reason: str = "") -> bool:
        """将 monitor 标记为过期."""
        return self.close_monitor(
            event_id, result=reason or "观测期已过",
            new_status="expired",
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def load_all(self) -> list[MonitorEvent]:
        """加载全部 monitor events."""
        return _load_jsonl(self._data_path)

    def get_active(self) -> list[MonitorEvent]:
        """返回所有 status=active 的 monitor."""
        return [e for e in self.load_all() if e.status == MonitorStatus.ACTIVE]

    def get_active_for_symbol(self, symbol: str) -> list[MonitorEvent]:
        """返回某股票的所有 active monitor."""
        return [
            e for e in self.load_all()
            if e.status == MonitorStatus.ACTIVE and e.symbol == symbol
        ]

    def get_triggered_recent(
        self,
        lookback_days: int = 7,
        reference_time: datetime | None = None,
    ) -> list[MonitorEvent]:
        """返回最近触发的 monitor events (供信号管线消费).

        Ref: ai-gold-miner calendar.py get_recently_triggered_monitors().
        """
        now = reference_time or datetime.now()
        cutoff = now - timedelta(days=lookback_days)
        result: list[MonitorEvent] = []

        for e in self.load_all():
            if e.status != MonitorStatus.TRIGGERED:
                continue
            if not e.triggered_at:
                continue
            try:
                triggered_dt = datetime.fromisoformat(e.triggered_at)
                if triggered_dt >= cutoff:
                    result.append(e)
            except (ValueError, TypeError):
                result.append(e)

        result.sort(key=lambda e: e.triggered_at or "", reverse=True)
        return result

    def get_by_symbol(self, symbol: str) -> list[MonitorEvent]:
        """返回某股票的所有 monitor events."""
        return [e for e in self.load_all() if e.symbol == symbol]

    def stats(self) -> dict[str, Any]:
        """统计信息."""
        events = self.load_all()
        active = [e for e in events if e.status == MonitorStatus.ACTIVE]
        triggered = [e for e in events if e.status == MonitorStatus.TRIGGERED]
        expired = [e for e in events if e.status == MonitorStatus.EXPIRED]

        by_type: dict[str, int] = {}
        for e in events:
            by_type[e.monitor_type.value] = by_type.get(e.monitor_type.value, 0) + 1

        return {
            "total": len(events),
            "active": len(active),
            "triggered": len(triggered),
            "expired": len(expired),
            "by_type": by_type,
            "by_symbol": _count_by(events, "symbol"),
        }


# ------------------------------------------------------------------
# JSONL 读写 helper
# ------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[MonitorEvent]:
    """从 JSONL 加载全部 MonitorEvent."""
    if not path.exists():
        return []
    events: list[MonitorEvent] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                events.append(MonitorEvent.from_dict(obj))
            except (json.JSONDecodeError, KeyError):
                continue
    except OSError as e:
        logger.warning(f"读取 monitor events 文件失败: {e}")
    return events


def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
    """追加一行到 JSONL."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning(f"追加 monitor event 失败: {e}")


def _rewrite_jsonl(path: Path, events: list[MonitorEvent]) -> None:
    """重写整个 JSONL 文件."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning(f"重写 monitor events 失败: {e}")


def _count_by(events: list[MonitorEvent], field: str) -> dict[str, int]:
    """按字段统计."""
    counts: dict[str, int] = {}
    for e in events:
        val = getattr(e, field, "")
        if val:
            counts[val] = counts.get(val, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10])
