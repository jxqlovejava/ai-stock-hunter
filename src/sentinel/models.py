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
    initial_stop_pct: Optional[float] = None  # 如 -0.08

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
            initial_stop_pct=_opt_float(data.get("initial_stop_pct")),
        )

    def market_value(self, price: float) -> float:
        if price <= 0 or self.quantity <= 0:
            return 0.0
        return price * self.quantity

    def cost_value(self) -> float:
        if self.entry_price <= 0 or self.quantity <= 0:
            return 0.0
        return self.entry_price * self.quantity


@dataclass(frozen=True)
class PortfolioLimits:
    """来自 portfolio.yaml 的仓位/风控上限（轻量）。"""

    total_capital: float = 500_000.0
    max_single_pct: float = 0.20
    max_total_exposure: float = 0.80
    min_cash_pct: float = 0.20
    single_stop_loss_pct: float = 0.08  # 单票浮亏告警（相对成本）
    portfolio_drawdown_pct: float = 0.05  # 组合相对成本的浮亏告警
    peak_drawdown_pct: float = 0.08  # 从持仓最高价回撤


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
        """单条卡（调试/兼容）。正式推送走 finalize 聚合人话。"""
        from .formatter import format_group_card

        return format_group_card([self], ts=ts)


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
        # 保留原始 alerts 供测试/调试；message 做人话聚合
        order = {AlertLevel.P0: 0, AlertLevel.P1: 1, AlertLevel.P2: 2}
        self.alerts.sort(key=lambda a: (order.get(a.level, 9), a.symbol, a.rule_id))

        from .formatter import format_sentinel_message

        self.message = format_sentinel_message(
            self.alerts,
            ts=ts,
            scanned=self.scanned,
            errors=self.errors,
        )
        # 去重后可能无文案（极端：仅 portfolio_loss 且单票）
        if not self.message.strip():
            self.silent = True
            self.message = ""
            return self
        self.silent = False
        return self


def _opt_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
