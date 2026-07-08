# -*- coding: utf-8 -*-
"""持仓实时状态追踪 — 价格 HWM + 三阶段动态止盈止损。

Phase 12: 补上"进场后价格顺向运行时动态调整止盈止损"的核心缺口。

三阶段状态机::

    INITIAL（进场止损=entry-ATR*m 或固定%）
      → max_favor ≥ breakeven_trigger（军规 r019: 20%）→ BREAKEVEN（止损=成本价）
      → max_favor ≥ trailing_trigger（军规 r028: 30%）  → TRAILING（止损=HWM-trail_pct，单向不回落）
      → last_price ≤ stop_price → STOP_HIT 预警

设计原则:
  - 不可变状态（frozen dataclass，借鉴 RiskState）
  - NaN 防御（坏价格不污染 HWM）
  - 阶段跃迁单向不可逆（止损失只上移不下移）
  - Decimal 精算（价格/止损用 Decimal，百分比用 float）
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from src.utils.decimal_utils import D

logger = logging.getLogger(__name__)

# 默认持久化路径
DEFAULT_POSITIONS_PATH = Path("data/positions.json")


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class StopStage(str, Enum):
    """止损阶段。单向跃迁: INITIAL → BREAKEVEN → TRAILING。"""
    INITIAL = "initial"       # 进场初始止损
    BREAKEVEN = "breakeven"   # 保本止损（浮盈触发 r019）
    TRAILING = "trailing"     # 移动止盈（浮盈触发 r028，跟踪 HWM）


class AlertType(str, Enum):
    """预警类型。"""
    STOP_LOSS = "stop_loss"       # 止损触发
    STAGE_TRANSITION = "stage_transition"  # 阶段跃迁


# ---------------------------------------------------------------------------
# 预警 DTO
# ---------------------------------------------------------------------------


@dataclass
class StopAlert:
    """止损/阶段跃迁预警。"""
    symbol: str
    name: str
    stop_stage: StopStage
    stop_price: float
    current_price: float
    message: str
    alert_type: AlertType = AlertType.STOP_LOSS
    severity: str = "CRITICAL"  # CRITICAL / WARNING / INFO
    created_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# PositionState — 每笔持仓的不可变快照
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionState:
    """单笔持仓的不可变状态。

    所有"变更"通过 ``replace()`` 返回新实例。
    借鉴 RiskState 的冻结模式 + NaN 防御。
    """

    symbol: str
    direction: str = "LONG"                # "LONG"（SHORT 预留）
    entry_price: float = 0.0
    entry_date: datetime = field(default_factory=datetime.now)
    quantity: int = 0
    name: str = ""

    # -- HWM 追踪 --
    high_price: float = 0.0                # 多仓所见最高价
    low_price: float = 0.0                 # 多仓所见最低价（初始=entry）
    last_price: float = 0.0

    # -- 止损状态 --
    stop_stage: StopStage = StopStage.INITIAL
    stop_price: float = 0.0                # 当前活跃止损价
    stop_note: str = ""                    # 阶段变更原因

    # -- 盈亏追踪 --
    unrealized_pnl_pct: float = 0.0
    max_favor_pct: float = 0.0             # 最大浮盈%
    max_adversity_pct: float = 0.0         # 最大浮亏%

    # -- 配置快照（建仓时从 TimeHorizonConfig 冻结）--
    initial_stop_pct: float = -0.02        # 固定止损%（负数，如 -0.02 = -2%）
    atr_multiplier: float = 2.0
    breakeven_trigger_pct: float = 0.20    # 军规 r019：浮盈>20%→保本
    trailing_trigger_pct: float = 0.30     # 军规 r028：浮盈>30%→ATR 移动止盈
    trailing_stop_pct: float = -0.05       # 从 HWM 回撤%（负数）

    def __post_init__(self):
        """强制精度: 价格字段用 float 但保持一致性。"""
        # 确保 high_price 初始 ≥ entry_price
        if self.high_price <= 0 and self.entry_price > 0:
            object.__setattr__(self, "high_price", self.entry_price)
        if self.low_price <= 0 and self.entry_price > 0:
            object.__setattr__(self, "low_price", self.entry_price)

    # ------------------------------------------------------------------
    # 不可变更新方法
    # ------------------------------------------------------------------

    def observe_price(self, price: float) -> PositionState:
        """观测新价格，更新 HWM + PnL，返回新状态。

        NaN/Inf 防御：坏读数直接返回自身（不污染状态）。
        借鉴 RiskState.observe_equity()。
        """
        if not math.isfinite(price) or price <= 0:
            return self

        hwm = max(self.high_price, price)
        lwm = min(self.low_price, price) if self.low_price > 0 else price

        if self.entry_price <= 0:
            return replace(
                self,
                high_price=hwm,
                low_price=lwm,
                last_price=price,
            )

        raw_pnl = (price - self.entry_price) / self.entry_price
        direction_mult = 1.0 if self.direction == "LONG" else -1.0
        direction_pnl = raw_pnl * direction_mult

        return replace(
            self,
            high_price=hwm,
            low_price=lwm,
            last_price=price,
            unrealized_pnl_pct=round(direction_pnl, 6),
            max_favor_pct=round(max(self.max_favor_pct, direction_pnl), 6),
            max_adversity_pct=round(min(self.max_adversity_pct, direction_pnl), 6),
        )

    def with_stop(self, stage: StopStage, price: float, note: str = "") -> PositionState:
        """过渡到新止损阶段。"""
        return replace(
            self,
            stop_stage=stage,
            stop_price=round(price, 2),
            stop_note=note,
        )

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "entry_date": self.entry_date.isoformat(),
            "quantity": self.quantity,
            "name": self.name,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "last_price": self.last_price,
            "stop_stage": self.stop_stage.value,
            "stop_price": self.stop_price,
            "stop_note": self.stop_note,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "max_favor_pct": self.max_favor_pct,
            "max_adversity_pct": self.max_adversity_pct,
            "initial_stop_pct": self.initial_stop_pct,
            "atr_multiplier": self.atr_multiplier,
            "breakeven_trigger_pct": self.breakeven_trigger_pct,
            "trailing_trigger_pct": self.trailing_trigger_pct,
            "trailing_stop_pct": self.trailing_stop_pct,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PositionState:
        return cls(
            symbol=d["symbol"],
            direction=d.get("direction", "LONG"),
            entry_price=float(d.get("entry_price", 0)),
            entry_date=_parse_datetime(d.get("entry_date", "")),
            quantity=int(d.get("quantity", 0)),
            name=d.get("name", ""),
            high_price=float(d.get("high_price", 0)),
            low_price=float(d.get("low_price", 0)),
            last_price=float(d.get("last_price", 0)),
            stop_stage=StopStage(d.get("stop_stage", "initial")),
            stop_price=float(d.get("stop_price", 0)),
            stop_note=d.get("stop_note", ""),
            unrealized_pnl_pct=float(d.get("unrealized_pnl_pct", 0)),
            max_favor_pct=float(d.get("max_favor_pct", 0)),
            max_adversity_pct=float(d.get("max_adversity_pct", 0)),
            initial_stop_pct=float(d.get("initial_stop_pct", -0.02)),
            atr_multiplier=float(d.get("atr_multiplier", 2.0)),
            breakeven_trigger_pct=float(d.get("breakeven_trigger_pct", 0.20)),
            trailing_trigger_pct=float(d.get("trailing_trigger_pct", 0.30)),
            trailing_stop_pct=float(d.get("trailing_stop_pct", -0.05)),
        )

    @classmethod
    def initial(
        cls,
        symbol: str,
        name: str = "",
        entry_price: float = 0.0,
        direction: str = "LONG",
        quantity: int = 0,
        stop_config: Optional[dict] = None,
    ) -> PositionState:
        """创建新持仓的初始状态。

        Args:
            stop_config: 可选配置覆盖，键:
                initial_stop_pct, atr_multiplier, breakeven_trigger_pct,
                trailing_trigger_pct, trailing_stop_pct
        """
        cfg = stop_config or {}
        pct = cfg.get("initial_stop_pct", -0.02)
        initial_stop = entry_price * (1.0 + pct) if entry_price > 0 else 0.0

        return cls(
            symbol=symbol,
            name=name,
            direction=direction,
            entry_price=entry_price,
            quantity=quantity,
            high_price=entry_price,
            low_price=entry_price,
            last_price=entry_price,
            stop_stage=StopStage.INITIAL,
            stop_price=round(initial_stop, 2),
            stop_note="初始止损",
            initial_stop_pct=cfg.get("initial_stop_pct", -0.02),
            atr_multiplier=cfg.get("atr_multiplier", 2.0),
            breakeven_trigger_pct=cfg.get("breakeven_trigger_pct", 0.20),
            trailing_trigger_pct=cfg.get("trailing_trigger_pct", 0.30),
            trailing_stop_pct=cfg.get("trailing_stop_pct", -0.05),
        )


# ---------------------------------------------------------------------------
# DynamicStopCalculator — 纯函数，计算止损水平
# ---------------------------------------------------------------------------


class DynamicStopCalculator:
    """纯函数计算器 — 根据阶段和状态计算止损价格。

    无副作用，无状态。所有方法为 static。
    """

    @staticmethod
    def initial_stop(state: PositionState, atr_value: Optional[float] = None) -> float:
        """阶段 1 止损: max(固定%, ATR×multiplier)。

        ATR 止损 = entry_price - ATR * atr_multiplier
        固定止损 = entry_price * (1 + initial_stop_pct)（initial_stop_pct 为负数）
        取两者中较高的（较紧的止损）。
        """
        if state.entry_price <= 0:
            return 0.0

        fixed = state.entry_price * (1.0 + state.initial_stop_pct)

        if atr_value and atr_value > 0 and state.atr_multiplier > 0:
            atr_stop = state.entry_price - atr_value * state.atr_multiplier
            return round(max(atr_stop, fixed), 2)

        return round(fixed, 2)

    @staticmethod
    def breakeven_stop(state: PositionState) -> float:
        """阶段 2 止损: 成本价。"""
        return round(state.entry_price, 2)

    @staticmethod
    def trailing_stop(state: PositionState) -> float:
        """阶段 3 止损: HWM × (1 + trailing_stop_pct)。

        trailing_stop_pct 为负数（如 -0.05 = HWM 回撤 5%）。
        止损失只上移不下移：新止损 = max(旧止损, HWM - trail)。
        """
        if state.high_price <= 0:
            return state.stop_price

        trail = state.high_price * (1.0 + state.trailing_stop_pct)
        # 止损失永不回落
        new_stop = max(trail, state.stop_price) if state.stop_price > 0 else trail
        return round(new_stop, 2)

    @staticmethod
    def determine_stage(state: PositionState) -> tuple[StopStage, float, str]:
        """根据当前浮盈判断止损阶段。

        Returns:
            (应处阶段, 止损价格, 原因说明)
        """
        favor = state.max_favor_pct

        # 已在 TRAILING 中 → 持续更新 trailing_stop
        if state.stop_stage == StopStage.TRAILING:
            new_stop = DynamicStopCalculator.trailing_stop(state)
            return (StopStage.TRAILING, new_stop, "追踪更新 (TRAILING 持续)")

        # 浮盈 ≥ 30% → 跃迁到 TRAILING（军规 r028）
        if favor >= state.trailing_trigger_pct:
            new_stop = DynamicStopCalculator.trailing_stop(state)
            return (StopStage.TRAILING, new_stop, f"浮盈 {favor:.1%} ≥ {state.trailing_trigger_pct:.0%}，启动移动止盈 (r028)")

        # 浮盈 ≥ 20% → 跃迁到 BREAKEVEN（军规 r019）
        if favor >= state.breakeven_trigger_pct:
            new_stop = DynamicStopCalculator.breakeven_stop(state)
            return (StopStage.BREAKEVEN, new_stop, f"浮盈 {favor:.1%} ≥ {state.breakeven_trigger_pct:.0%}，止损上移至成本价 (r019)")

        # 保持 INITIAL
        return (state.stop_stage, state.stop_price, "")


# ---------------------------------------------------------------------------
# PositionStateManager — 管理所有持仓，持久化，预警
# ---------------------------------------------------------------------------


class PositionStateManager:
    """持仓状态管理器。

    管理所有开仓头寸的生命周期: 开仓 → 价格更新 → 阶段跃迁 → 平仓。
    JSON 持久化到 ``data/positions.json``。

    用法::

        mgr = PositionStateManager()
        mgr.open("600519", "贵州茅台", entry_price=1480.0)
        updated, alerts = mgr.update_price("600519", 1550.0)
        # alerts 可能包含 STAGE_TRANSITION 或 STOP_LOSS
        mgr.close("600519")
    """

    BREAKEVEN_ACTIVATED = "BREAKEVEN_ACTIVATED"
    TRAILING_ACTIVATED = "TRAILING_ACTIVATED"
    STOP_HIT = "STOP_HIT"

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else DEFAULT_POSITIONS_PATH
        self._positions: dict[str, PositionState] = {}
        self._load()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def open(
        self,
        symbol: str,
        name: str = "",
        entry_price: float = 0.0,
        direction: str = "LONG",
        quantity: int = 0,
        stop_config: Optional[dict] = None,
    ) -> PositionState:
        """创建新持仓状态。已存在则跳过不覆盖。"""
        if symbol in self._positions:
            logger.warning("持仓 %s 已存在，跳过 open()", symbol)
            return self._positions[symbol]

        state = PositionState.initial(
            symbol=symbol,
            name=name,
            entry_price=entry_price,
            direction=direction,
            quantity=quantity,
            stop_config=stop_config,
        )
        self._positions[symbol] = state
        self._save()
        logger.info(
            "持仓追踪已启动: %s %s @ %.2f (止损 %.2f)",
            symbol, name, entry_price, state.stop_price,
        )
        return state

    def update_price(
        self,
        symbol: str,
        price: float,
        atr_value: Optional[float] = None,
    ) -> tuple[Optional[PositionState], list[StopAlert]]:
        """观测新价格，更新 HWM，可能触发止损预警或阶段跃迁。

        Returns:
            (updated_state, alerts)。持仓不存在则返回 (None, [])。
        """
        pos = self._positions.get(symbol)
        if pos is None:
            return (None, [])

        alerts: list[StopAlert] = []

        # 1. 观测价格
        pos2 = pos.observe_price(price)

        # 2. 检查止损触发
        if pos2.stop_price > 0 and pos2.last_price > 0 and pos2.last_price <= pos2.stop_price:
            alerts.append(StopAlert(
                symbol=symbol,
                name=pos2.name,
                stop_stage=pos2.stop_stage,
                stop_price=pos2.stop_price,
                current_price=pos2.last_price,
                message=(
                    f"止损触发: 现价 {pos2.last_price:.2f} ≤ 止损价 {pos2.stop_price:.2f}"
                    f"（阶段: {pos2.stop_stage.value}），建议平仓"
                ),
                alert_type=AlertType.STOP_LOSS,
                severity="CRITICAL",
            ))

        # 3. 检查阶段跃迁
        new_stage, new_stop, reason = DynamicStopCalculator.determine_stage(pos2)
        if new_stage != pos2.stop_stage:
            pos2 = pos2.with_stop(new_stage, new_stop, reason)
            alert_type = (
                AlertType.STAGE_TRANSITION
                if new_stage in (StopStage.BREAKEVEN, StopStage.TRAILING)
                else AlertType.STOP_LOSS
            )
            alerts.append(StopAlert(
                symbol=symbol,
                name=pos2.name,
                stop_stage=new_stage,
                stop_price=new_stop,
                current_price=pos2.last_price,
                message=f"止损阶段跃迁: {reason}，止损价 → {new_stop:.2f}",
                alert_type=alert_type,
                severity="INFO" if new_stage == StopStage.BREAKEVEN else "WARNING",
            ))
        elif new_stage == StopStage.TRAILING and new_stop != pos2.stop_price:
            # 已在 TRAILING 中，止损价上移
            pos2 = pos2.with_stop(new_stage, new_stop, reason)

        self._positions[symbol] = pos2
        self._save()
        return (pos2, alerts)

    def close(self, symbol: str) -> Optional[PositionState]:
        """平仓并从活跃状态中移除。返回最后状态。"""
        state = self._positions.pop(symbol, None)
        if state:
            self._save()
            logger.info(
                "持仓状态已清除: %s (入场 %.2f → 出场 %.2f, 最大浮盈 %.1f%%)",
                symbol,
                state.entry_price,
                state.last_price,
                state.max_favor_pct * 100,
            )
        return state

    def update_quantity(self, symbol: str, quantity: int) -> Optional[PositionState]:
        """更新持仓数量（如加仓/减仓）。"""
        pos = self._positions.get(symbol)
        if pos is None:
            return None
        new_pos = replace(pos, quantity=quantity)
        self._positions[symbol] = new_pos
        self._save()
        return new_pos

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def get(self, symbol: str) -> Optional[PositionState]:
        """获取某标的持仓状态。"""
        return self._positions.get(symbol)

    def get_all(self) -> list[PositionState]:
        """获取所有开仓头寸。"""
        return list(self._positions.values())

    def is_open(self, symbol: str) -> bool:
        """检查某标的是否有开仓头寸。"""
        return symbol in self._positions

    @property
    def count(self) -> int:
        return len(self._positions)

    def clear(self) -> None:
        """清空所有持仓状态。"""
        self._positions.clear()
        self._save()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """持久化到 JSON 文件。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, dict] = {}
        for sym, state in self._positions.items():
            data[sym] = state.to_dict()
        try:
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error("无法保存持仓状态到 %s: %s", self._path, e)

    def _load(self) -> None:
        """从 JSON 文件加载。"""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._positions = {}
            for sym, d in raw.items():
                try:
                    self._positions[sym] = PositionState.from_dict(d)
                except (KeyError, TypeError, ValueError) as e:
                    logger.error("跳过损坏的持仓记录 %s: %s", sym, e)
            logger.info("已加载 %d 个持仓状态", len(self._positions))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("无法加载持仓状态: %s", e)
            self._positions = {}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _parse_datetime(s: str) -> datetime:
    """解析 ISO 格式时间戳，失败返回当前时间。"""
    if not s:
        return datetime.now()
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return datetime.now()
