# -*- coding: utf-8 -*-
"""风控运行时状态 — 不可变快照。

借鉴 RiskGuard ``state.py`` 设计：记录权益高点 (high-water mark)、熔断开关、
各策略入役时间（隔离观察期）。所有"变更"都返回新的 RiskState，绝不原地修改
——历史状态因此永远可追溯、可回放。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Mapping, Optional


def _freeze(m: Mapping[str, datetime]) -> Mapping[str, datetime]:
    return MappingProxyType(dict(m))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RiskState:
    """引擎在某一时刻的风控状态快照（不可变）。

    属性:
        high_water_mark: 观测到的权益历史最高点，回撤基准。
        last_equity: 最近一次观测到的权益。
        breaker_tripped: 总亏损熔断是否已触发。
        tripped_at: 熔断触发时间。
        trip_reason: 熔断触发原因的可读描述。
        strategy_inception: 各策略首次被登记的时间，隔离观察期由此计算。
    """

    high_water_mark: float = 0.0
    last_equity: float = 0.0
    breaker_tripped: bool = False
    tripped_at: Optional[datetime] = None
    trip_reason: str = ""
    strategy_inception: Mapping[str, datetime] = field(default_factory=dict)
    consecutive_stops: int = 0
    """连续止损次数（无盈利平仓时累计，盈利复位）。军规 r017 / 冷却逻辑读取。"""
    cooling_until: Optional[datetime] = None
    """连亏冷却到期时间（UTC）。达阈值后，此时间之前禁止自动开新仓。"""

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_inception", _freeze(self.strategy_inception))

    # ------------------------------------------------------------------
    # 派生量
    # ------------------------------------------------------------------
    @property
    def drawdown(self) -> float:
        """当前相对高点的回撤。

        0.0 表示在高点，0.2 表示回撤 20%。权益无效时返回 0.0。
        """
        if self.high_water_mark <= 0.0:
            return 0.0
        return max(0.0, 1.0 - self.last_equity / self.high_water_mark)

    # ------------------------------------------------------------------
    # 不可变更新方法
    # ------------------------------------------------------------------
    def observe_equity(self, equity: float) -> "RiskState":
        """观测一笔新的权益值，返回更新了 HWM / last_equity 的新状态。

        **NaN 防御**: ``NaN`` / ``±inf`` 的权益（feed 抖动、除零、坏 tick）
        会被直接**忽略**，返回原状态不变。绝不能让 NaN 污染 last_equity——
        那会让 drawdown 恒算成 NaN、回撤熔断从此永不触发 (fail-open)。
        """
        if not math.isfinite(equity):
            return self
        hwm = max(self.high_water_mark, equity)
        return replace(self, high_water_mark=hwm, last_equity=equity)

    def trip(self, reason: str, now: Optional[datetime] = None) -> "RiskState":
        """触发熔断，返回新状态。已触发则幂等原样返回。"""
        if self.breaker_tripped:
            return self
        return replace(
            self,
            breaker_tripped=True,
            tripped_at=now or _utc_now(),
            trip_reason=reason,
        )

    def reset_breaker(self, now: Optional[datetime] = None) -> "RiskState":
        """人工复盘后重置熔断，并把 HWM 归位到当前权益。

        避免立刻二次触发：例如从 100→85（-15%）熔断，reset 后 HWM=85，
        后续从 85 涨回 100 的过程中不会再因与旧 HWM(100) 比较而误触发。
        """
        _ = now  # 保留参数一致性，当前版本不记录 reset 时间
        return replace(
            self,
            breaker_tripped=False,
            tripped_at=None,
            trip_reason="",
            high_water_mark=self.last_equity,
        )

    def register_strategy(
        self, strategy_id: str, now: Optional[datetime] = None
    ) -> "RiskState":
        """登记一个策略的入役时间。已存在则不覆盖（保留最早时间）。"""
        if strategy_id in self.strategy_inception:
            return self
        merged = dict(self.strategy_inception)
        merged[strategy_id] = now or _utc_now()
        return replace(self, strategy_inception=merged)

    def strategy_age_days(
        self, strategy_id: str, now: Optional[datetime] = None
    ) -> Optional[float]:
        """策略入役至今的天数；未登记返回 None。"""
        inception = self.strategy_inception.get(strategy_id)
        if inception is None:
            return None
        return ((now or _utc_now()) - inception).total_seconds() / 86400.0

    # ------------------------------------------------------------------
    # 连续止损计数 & 冷却 (P0-3)
    # ------------------------------------------------------------------
    def record_stop(
        self, now: Optional[datetime] = None, cooldown_days: int = 3
    ) -> "RiskState":
        """记录一笔止损平仓 → 连亏计数 +1，冷却窗口从本次止损起算。

        达到阈值后由引擎的 ``_check_cooldown`` 暂停自动开仓。``cooldown_days``
        ≤ 0 表示不启用时间冷却（仅计数，冷却判据交给调用方）。
        """
        now = now or _utc_now()
        cooling_until = self.cooling_until
        if cooldown_days > 0:
            cooling_until = now + timedelta(days=cooldown_days)
        return replace(
            self,
            consecutive_stops=self.consecutive_stops + 1,
            cooling_until=cooling_until,
        )

    def record_win(self) -> "RiskState":
        """记录一笔盈利平仓 → 连亏计数复位，冷却解除。"""
        if self.consecutive_stops == 0 and self.cooling_until is None:
            return self
        return replace(self, consecutive_stops=0, cooling_until=None)

    def advance_time(self, now: Optional[datetime] = None) -> "RiskState":
        """时间推进 — 冷却窗口无新止损发生时，连亏计数自动复位。

        冷却到期前若再次止损，计数继续累计（冷却窗口随之顺延）。
        """
        now = now or _utc_now()
        if (
            self.consecutive_stops > 0
            and self.cooling_until is not None
            and now >= self.cooling_until
        ):
            return replace(self, consecutive_stops=0, cooling_until=None)
        return self

    def in_cooldown(self, now: Optional[datetime] = None) -> bool:
        """是否处于冷却窗口内（``cooling_until`` 未过期）。"""
        now = now or _utc_now()
        return self.cooling_until is not None and now < self.cooling_until

    def cooldown_remaining_days(self, now: Optional[datetime] = None) -> float:
        """冷却剩余天数（已过期/未触发 → 0.0）。"""
        now = now or _utc_now()
        if self.cooling_until is None or now >= self.cooling_until:
            return 0.0
        return (self.cooling_until - now).total_seconds() / 86400.0

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------
    @classmethod
    def initial(cls, equity: float = 0.0) -> "RiskState":
        """用初始权益构造起始状态，高点即为初始权益。"""
        return cls(high_water_mark=equity, last_equity=equity)

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """转为可 JSON 序列化的 dict。"""
        return {
            "high_water_mark": self.high_water_mark,
            "last_equity": self.last_equity,
            "breaker_tripped": self.breaker_tripped,
            "tripped_at": self.tripped_at.isoformat() if self.tripped_at else None,
            "trip_reason": self.trip_reason,
            "drawdown": self.drawdown,
            "strategy_inception": {
                k: v.isoformat() for k, v in self.strategy_inception.items()
            },
            "consecutive_stops": self.consecutive_stops,
            "cooling_until": self.cooling_until.isoformat() if self.cooling_until else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RiskState":
        """从 dict 恢复 RiskState。"""
        return cls(
            high_water_mark=float(d.get("high_water_mark", 0.0)),
            last_equity=float(d.get("last_equity", 0.0)),
            breaker_tripped=bool(d.get("breaker_tripped", False)),
            tripped_at=(
                datetime.fromisoformat(d["tripped_at"])
                if d.get("tripped_at")
                else None
            ),
            trip_reason=str(d.get("trip_reason", "")),
            strategy_inception={
                k: datetime.fromisoformat(v)
                for k, v in d.get("strategy_inception", {}).items()
            },
            consecutive_stops=int(d.get("consecutive_stops", 0)),
            cooling_until=(
                datetime.fromisoformat(d["cooling_until"])
                if d.get("cooling_until")
                else None
            ),
        )
