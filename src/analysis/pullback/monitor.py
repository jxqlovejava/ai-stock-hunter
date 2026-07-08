# -*- coding: utf-8 -*-
"""入场条件监控 (EntryConditionMonitor)。

管理"等回调"的条件单:
  - 持久化到 data/pullback_watch.json
  - 支持增删查
  - 每次检查更新条件满足状态
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .detector import PullbackDetector
from .schemas import PullbackStatus, PullbackTier, WatchEntry

logger = logging.getLogger(__name__)

DEFAULT_WATCH_PATH = "data/pullback_watch.json"


class EntryConditionMonitor:
    """入场条件监控。

    用法:
        monitor = EntryConditionMonitor(detector, data_provider)
        monitor.add("002460", name="赣锋锂业")
        monitor.check_all()  # 返回状态变更列表
    """

    def __init__(
        self,
        detector: Optional[PullbackDetector] = None,
        data_provider=None,
        watch_path: str = DEFAULT_WATCH_PATH,
    ):
        self._detector = detector or PullbackDetector()
        self._data = data_provider
        self._watch_path = Path(watch_path)
        self._lock = threading.Lock()
        self._entries: dict[str, WatchEntry] = {}
        self._load()

    # ── CRUD ──

    def add(self, symbol: str, *, name: str = "", trigger_condition: str = "") -> WatchEntry:
        """添加标的到监控列表。"""
        with self._lock:
            entry = WatchEntry(
                symbol=symbol,
                name=name,
                added_at=datetime.now().isoformat(),
                trigger_condition=trigger_condition,
            )
            self._entries[symbol] = entry
            self._save()
            logger.info("加入回调监控: %s %s", symbol, name)
            return entry

    def remove(self, symbol: str) -> bool:
        """移除监控标的。"""
        with self._lock:
            if symbol in self._entries:
                del self._entries[symbol]
                self._save()
                logger.info("移除回调监控: %s", symbol)
                return True
            return False

    def list_all(self) -> list[WatchEntry]:
        """列出所有监控标的。"""
        with self._lock:
            return list(self._entries.values())

    def get(self, symbol: str) -> Optional[WatchEntry]:
        """获取单个监控条目。"""
        with self._lock:
            return self._entries.get(symbol)

    # ── 检查 ──

    def check_one(self, symbol: str) -> Optional[WatchEntry]:
        """检查单个标的的条件满足状态。

        Returns:
            更新后的 WatchEntry，或 None（标的未在监控列表中）
        """
        entry = self.get(symbol)
        if entry is None:
            return None

        try:
            if self._data is None:
                return entry

            daily_bars = self._data.get_daily_bars(symbol, count=60)
            if not daily_bars:
                return entry

            minute_data = None
            try:
                if hasattr(self._data, 'get_minute_bars'):
                    minute_data = self._data.get_minute_bars(symbol)
            except Exception:
                pass

            state = self._detector.detect(
                symbol,
                daily_bars,
                name=entry.name,
                minute_data=minute_data,
            )

            with self._lock:
                entry.last_check_at = datetime.now().isoformat()
                entry.last_status = state.status
                entry.trigger_price = state.trigger_price
                entry.trigger_condition = state.entry_condition

                if state.tier == PullbackTier.READY:
                    entry.condition_met_count += 1
                else:
                    entry.condition_met_count = 0

                self._save()

            return entry

        except Exception as e:
            logger.error("检查条件失败 [%s]: %s", symbol, e)
            return entry

    def check_all(self) -> dict[str, list[WatchEntry]]:
        """检查全部监控标的，返回状态变更分组。

        Returns:
            {
                "upgraded": [...],   # WATCH → READY
                "unchanged": [...],
                "degraded": [...],   # READY/WATCH → BLOCKED
                "new_signals": [...],# 新增操纵信号
            }
        """
        result: dict[str, list[WatchEntry]] = {
            "upgraded": [],
            "unchanged": [],
            "degraded": [],
            "new_signals": [],
        }

        for symbol, old_entry in list(self._entries.items()):
            new_entry = self.check_one(symbol)
            if new_entry is None:
                continue

            old_tier = _status_to_tier(old_entry.last_status)
            new_tier = _status_to_tier(new_entry.last_status)

            if new_tier == PullbackTier.READY and old_tier != PullbackTier.READY:
                result["upgraded"].append(new_entry)
                logger.info("🟢 [%s] 条件满足！回调到位", symbol)
            elif new_tier == PullbackTier.BLOCKED and old_tier != PullbackTier.BLOCKED:
                result["degraded"].append(new_entry)
                logger.warning("🔴 [%s] 条件恶化，已排除", symbol)
            else:
                result["unchanged"].append(new_entry)

        return result

    # ── 持久化 ──

    def _load(self):
        """从 JSON 文件加载监控列表。"""
        if not self._watch_path.exists():
            return
        try:
            with open(self._watch_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                entry = WatchEntry(**item)
                self._entries[entry.symbol] = entry
            logger.info("加载回调监控列表: %d 条", len(self._entries))
        except Exception as e:
            logger.error("加载监控列表失败: %s", e)

    def _save(self):
        """保存监控列表到 JSON 文件。"""
        os.makedirs(self._watch_path.parent, exist_ok=True)
        try:
            data = [_entry_to_dict(e) for e in self._entries.values()]
            with open(self._watch_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("保存监控列表失败: %s", e)


def _status_to_tier(status: PullbackStatus) -> PullbackTier:
    """将 PullbackStatus 映射到 PullbackTier。"""
    mapping = {
        PullbackStatus.SETUP: PullbackTier.READY,
        PullbackStatus.ACTIVE: PullbackTier.WATCH,
        PullbackStatus.TRAP: PullbackTier.BLOCKED,
        PullbackStatus.BREAK: PullbackTier.BLOCKED,
        PullbackStatus.NONE: PullbackTier.WATCH,
    }
    return mapping.get(status, PullbackTier.WATCH)


def _entry_to_dict(entry: WatchEntry) -> dict:
    """将 WatchEntry 转为可 JSON 序列化的 dict。"""
    return {
        "symbol": entry.symbol,
        "name": entry.name,
        "added_at": entry.added_at,
        "trigger_price": entry.trigger_price,
        "trigger_condition": entry.trigger_condition,
        "last_check_at": entry.last_check_at,
        "last_status": entry.last_status.value if entry.last_status else "",
        "condition_met_count": entry.condition_met_count,
        "notified": entry.notified,
    }
