# -*- coding: utf-8 -*-
"""哨兵状态：价格历史 + 冷却。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class SentinelStateStore:
    """JSON 状态文件。"""

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, Any] = {"symbols": {}, "cooling": {}, "meta": {}}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
                self._data.setdefault("symbols", {})
                self._data.setdefault("cooling", {})
                self._data.setdefault("meta", {})
        except (OSError, json.JSONDecodeError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def get_symbol(self, symbol: str) -> dict[str, Any]:
        return self._data["symbols"].setdefault(
            symbol,
            {"last_price": None, "history": [], "amplitude_alerted": [], "day": ""},
        )

    def set_symbol(self, symbol: str, state: dict[str, Any]) -> None:
        self._data["symbols"][symbol] = state

    def is_cooling(self, key: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        until = self._data["cooling"].get(key)
        if until is None:
            return False
        return float(until) > now

    def set_cooling(self, key: str, minutes: int, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._data["cooling"][key] = now + max(0, minutes) * 60

    def prune_cooling(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        cool = self._data.get("cooling") or {}
        self._data["cooling"] = {k: v for k, v in cool.items() if float(v) > now}
