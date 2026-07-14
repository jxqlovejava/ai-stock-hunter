# -*- coding: utf-8 -*-
"""哨兵数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AlertLevel(str, Enum):
    """推送级别。"""

    P0 = "P0"  # 必达：止损触及/逼近
    P1 = "P1"  # 行动：破成本、急跌急涨
    P2 = "P2"  # 知情：振幅、跳变


@dataclass(frozen=True)
class PositionSnapshot:
    """持仓快照（来自 positions.json）。"""

    symbol: str
    name: str = ""
    direction: str = "LONG"
    entry_price: float = 0.0
    quantity: float = 0.0
    stop_price: Optional[float] = None
    high_price: Optional[float] = None
    last_price: Optional[float] = None

    @classmethod
    def from_dict(cls, symbol: str, data: dict) -> "PositionSnapshot":
        return cls(
            symbol=str(data.get("symbol") or symbol),
            name=str(data.get("name") or ""),
            direction=str(data.get("direction") or "LONG").upper(),
            entry_price=float(data.get("entry_price") or 0.0),
            quantity=float(data.get("quantity") or 0.0),
            stop_price=_opt_float(data.get("stop_price")),
            high_price=_opt_float(data.get("high_price")),
            last_price=_opt_float(data.get("last_price")),
        )


@dataclass(frozen=True)
class QuoteSnapshot:
    """实时报价。"""

    symbol: str
    name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    prev_close: Optional[float] = None
    source: str = "tencent"


@dataclass
class SentinelAlert:
    """单条预警。"""

    level: AlertLevel
    rule_id: str
    symbol: str
    name: str
    title: str
    body: str
    price: float = 0.0
    cooling_key: str = ""
    cooling_minutes: int = 15

    def format_card(self, ts: str = "") -> str:
        head = f"【{self.level.value}·{self.title}】{self.name} {self.symbol}"
        lines = [head, self.body]
        if self.price > 0:
            lines.append(f"现价 {self.price:.2f}" + (f" · {ts}" if ts else ""))
        return "\n".join(lines)


@dataclass
class SentinelResult:
    """一轮扫描结果。"""

    alerts: list[SentinelAlert] = field(default_factory=list)
    scanned: int = 0
    errors: list[str] = field(default_factory=list)
    silent: bool = True
    message: str = ""

    def finalize(self, ts: str = "") -> "SentinelResult":
        if not self.alerts:
            self.silent = True
            self.message = ""
            return self
        # P0 优先，其次 P1、P2
        order = {AlertLevel.P0: 0, AlertLevel.P1: 1, AlertLevel.P2: 2}
        self.alerts.sort(key=lambda a: (order.get(a.level, 9), a.symbol, a.rule_id))
        cards = [a.format_card(ts) for a in self.alerts]
        self.message = "\n\n".join(cards)
        if self.errors:
            self.message += "\n\n⚠️ " + "; ".join(self.errors[:3])
        self.silent = False
        return self


def _opt_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
