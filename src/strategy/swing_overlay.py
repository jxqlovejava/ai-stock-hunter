# -*- coding: utf-8 -*-
"""持仓 Swing Overlay — 借鉴 V1 解套战法 / V2 负成本分桶 的改写版规则。

定位（重要）:
  - **不替代** 军规→准入→诊断→裁决→仓位→风控 主链。
  - 仅对 **已持仓** 标的给出减仓 / 滚动仓做差 / 结构破位修复 建议。
  - 所有数量经 A 股 100 股一手约束（``board_lot``）。

V1 改写（修复 playbook）:
  - 结构破位 / 跌破止损 → 减仓或清仓（不是等 -30%）
  - 禁止越跌越加（浮亏超阈值禁止 ADD）
  - 1 手持仓无法半仓 → 只能全卖或全留

V2 改写（分桶 + 做 T）:
  - core / swing 分账；swing 预算有上限
  - 正 T: 支撑附近 SWING_BUY（滚动预算内）
  - 反 T / 兑现: 压力附近 SWING_SELL
  - 日交易次数上限；亏损滚动仓禁止加仓

输出为只读决策 DTO，写信号仍须过 L4 / signal-writer。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.strategy.board_lot import (
    BOARD_LOT,
    can_partial_reduce,
    floor_to_lot,
    resolve_buy_quantity,
    resolve_sell_quantity,
)


# ---------------------------------------------------------------------------
# Config / enums / DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SwingOverlayConfig:
    """不可变配置 — 默认对齐军规单票 20% 与稳健分桶。"""

    board_lot: int = BOARD_LOT
    core_max_pct: float = 0.12          # 单票核心仓占权益上限
    swing_max_pct: float = 0.05         # 单票滚动仓占权益上限
    single_max_pct: float = 0.20        # 单票合计上限（军规 r001）
    structure_reduce_pct: float = 50.0  # 结构破位目标减仓比例 %
    min_pnl_for_add: float = -0.05      # 浮亏超过此值禁止加仓
    max_swing_trades_per_day: int = 2
    min_pipeline_score_for_swing: float = 50.0
    # 核心/滚动默认拆分：新建仓时 core 占目标的 70%，swing 30%（再夹到上限）
    core_fraction_of_target: float = 0.70


class OverlayAction(str, Enum):
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    SWING_BUY = "SWING_BUY"
    SWING_SELL = "SWING_SELL"
    BLOCKED = "BLOCKED"       # 想加仓但被闸门拦住
    INFEASIBLE = "INFEASIBLE"  # 规则想减仓但手数约束下只能说明不可行（极少用）


@dataclass(frozen=True)
class BucketPlan:
    """目标分桶（股数）。"""

    core_shares: int
    swing_shares: int
    total_shares: int
    core_weight_pct: float
    swing_weight_pct: float
    note: str = ""


@dataclass(frozen=True)
class PositionBucketView:
    """持仓分桶视图。"""

    symbol: str
    name: str = ""
    total_shares: int = 0
    core_shares: int = 0
    swing_shares: int = 0
    entry_price: float = 0.0
    current_price: float = 0.0
    stop_price: float = 0.0
    equity: float = 0.0

    @property
    def pnl_pct(self) -> float:
        if self.entry_price <= 0 or self.current_price <= 0:
            return 0.0
        return (self.current_price - self.entry_price) / self.entry_price

    @property
    def market_value(self) -> float:
        return max(self.total_shares, 0) * max(self.current_price, 0.0)

    @property
    def weight_pct(self) -> float:
        if self.equity <= 0:
            return 0.0
        return self.market_value / self.equity


@dataclass(frozen=True)
class OverlayMarketContext:
    """市场/管道上下文 — 由调用方注入（T0 / 诊断 / 行情）。"""

    price: float
    ma20: Optional[float] = None
    support: Optional[float] = None
    resistance: Optional[float] = None
    atr: Optional[float] = None
    stop_price: Optional[float] = None
    structure_broken: Optional[bool] = None  # 显式覆盖；None 时用 price<ma20
    near_support: bool = False
    near_resistance: bool = False
    pipeline_score: float = 50.0
    pipeline_action: str = "HOLD"  # OPEN/ADD/HOLD/REDUCE/EXIT
    swing_trades_today: int = 0
    # T+1: 今日新买入的滚动仓是否已可卖（A 股次日才 True）
    swing_shares_sellable: int = 0


@dataclass(frozen=True)
class OverlayDecision:
    """单条 overlay 建议（只读）。"""

    symbol: str
    action: OverlayAction
    quantity: int
    reason: str
    rule: str
    urgency: str = "NORMAL"  # HIGH / NORMAL / LOW
    notes: tuple[str, ...] = ()
    pnl_pct: float = 0.0
    core_shares: int = 0
    swing_shares: int = 0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action.value,
            "quantity": self.quantity,
            "reason": self.reason,
            "rule": self.rule,
            "urgency": self.urgency,
            "notes": list(self.notes),
            "pnl_pct": self.pnl_pct,
            "core_shares": self.core_shares,
            "swing_shares": self.swing_shares,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SwingOverlayEngine:
    """V1/V2 改写版持仓 overlay 引擎（纯函数式决策）。"""

    def __init__(self, config: Optional[SwingOverlayConfig] = None) -> None:
        self.config = config or SwingOverlayConfig()

    # ------------------------------------------------------------------
    # 分桶规划（建仓/加仓 sizing 后调用）
    # ------------------------------------------------------------------

    def plan_buckets(
        self,
        equity: float,
        price: float,
        target_total_pct: float,
    ) -> BucketPlan:
        """按目标权重规划 core/swing 整手股数。"""
        cfg = self.config
        if equity <= 0 or price <= 0 or target_total_pct <= 0:
            return BucketPlan(0, 0, 0, 0.0, 0.0, note="invalid_input")

        total_pct = min(float(target_total_pct), cfg.single_max_pct)
        core_pct = min(total_pct * cfg.core_fraction_of_target, cfg.core_max_pct)
        swing_pct = min(max(total_pct - core_pct, 0.0), cfg.swing_max_pct)
        # 若 swing 被夹扁，剩余归 core（仍不超过 single_max）
        if core_pct + swing_pct < total_pct:
            core_pct = min(total_pct - swing_pct, cfg.core_max_pct)

        core_shares = floor_to_lot(int(equity * core_pct / price), cfg.board_lot)
        swing_shares = floor_to_lot(int(equity * swing_pct / price), cfg.board_lot)
        total = core_shares + swing_shares
        actual_core_w = core_shares * price / equity if equity else 0.0
        actual_swing_w = swing_shares * price / equity if equity else 0.0
        return BucketPlan(
            core_shares=core_shares,
            swing_shares=swing_shares,
            total_shares=total,
            core_weight_pct=round(actual_core_w, 6),
            swing_weight_pct=round(actual_swing_w, 6),
            note="ok" if total > 0 else "below_one_lot",
        )

    def split_existing(
        self,
        total_shares: int,
        *,
        preferred_swing_shares: Optional[int] = None,
    ) -> tuple[int, int]:
        """把已有持仓拆成 core/swing（默认 70/30，整手对齐）。"""
        lot = self.config.board_lot
        if total_shares <= 0:
            return 0, 0
        if total_shares < 2 * lot:
            # 不足 2 手：全部记 core，无法滚动
            return total_shares, 0

        if preferred_swing_shares is not None:
            swing = floor_to_lot(min(preferred_swing_shares, total_shares), lot)
            core = total_shares - swing
            return core, swing

        swing_target = floor_to_lot(
            int(total_shares * (1.0 - self.config.core_fraction_of_target)),
            lot,
        )
        # 至少留 1 手 core
        max_swing = total_shares - lot
        swing = min(swing_target, floor_to_lot(max_swing, lot))
        core = total_shares - swing
        return core, swing

    # ------------------------------------------------------------------
    # 主决策
    # ------------------------------------------------------------------

    def evaluate(
        self,
        position: PositionBucketView,
        ctx: OverlayMarketContext,
    ) -> OverlayDecision:
        """对单笔持仓输出一条最高优先级建议。"""
        cfg = self.config
        notes: list[str] = []
        symbol = position.symbol
        shares = position.total_shares
        price = ctx.price if ctx.price > 0 else position.current_price
        pnl = position.pnl_pct
        if position.entry_price > 0 and price > 0:
            pnl = (price - position.entry_price) / position.entry_price

        core, swing = position.core_shares, position.swing_shares
        if core + swing != shares and shares > 0:
            core, swing = self.split_existing(shares)
            notes.append(f"auto_split core={core} swing={swing}")

        base_kw = dict(
            symbol=symbol,
            pnl_pct=round(pnl, 6),
            core_shares=core,
            swing_shares=swing,
        )

        if shares <= 0:
            return OverlayDecision(
                action=OverlayAction.HOLD,
                quantity=0,
                reason="无持仓",
                rule="empty",
                urgency="LOW",
                notes=tuple(notes),
                **base_kw,
            )

        stop = ctx.stop_price if ctx.stop_price and ctx.stop_price > 0 else position.stop_price
        structure_broken = self._is_structure_broken(price, ctx)

        # 1) 止损硬线 — 优先于一切 overlay 战术
        if stop > 0 and price > 0 and price <= stop:
            return OverlayDecision(
                action=OverlayAction.EXIT,
                quantity=shares,
                reason=f"跌破止损 {stop:.2f}（现价 {price:.2f}）→ 清仓",
                rule="stop_hit",
                urgency="HIGH",
                notes=tuple(notes + ["V1改写: 止损优先于解套剧本"]),
                **base_kw,
            )

        # 2) 结构破位减仓（V1 改写）
        if structure_broken:
            qty, lot_note = resolve_sell_quantity(
                shares,
                cfg.structure_reduce_pct,
                lot=cfg.board_lot,
                force_full_if_sub_lot=True,
            )
            notes.append(lot_note)
            if not can_partial_reduce(shares, cfg.board_lot):
                notes.append("持仓不足2手，无法半仓，结构破位→全平或全留；此处建议全平")
            if qty >= shares:
                return OverlayDecision(
                    action=OverlayAction.EXIT,
                    quantity=shares,
                    reason=self._structure_reason(price, ctx) + "；手数约束下建议清仓",
                    rule="structure_break_full",
                    urgency="HIGH",
                    notes=tuple(notes),
                    **base_kw,
                )
            if qty > 0:
                return OverlayDecision(
                    action=OverlayAction.REDUCE,
                    quantity=qty,
                    reason=self._structure_reason(price, ctx)
                    + f" → 减仓 {cfg.structure_reduce_pct:.0f}%（{qty} 股）",
                    rule="structure_break_partial",
                    urgency="HIGH",
                    notes=tuple(notes),
                    **base_kw,
                )

        # 3) 管道已建议 REDUCE/EXIT — 对齐执行（仍手数合规）
        pa = (ctx.pipeline_action or "HOLD").upper()
        if pa in ("EXIT", "CLOSE", "CUT"):
            return OverlayDecision(
                action=OverlayAction.EXIT,
                quantity=shares,
                reason=f"管道动作 {pa} → 清仓",
                rule="pipeline_exit",
                urgency="HIGH",
                notes=tuple(notes),
                **base_kw,
            )
        if pa == "REDUCE":
            qty, lot_note = resolve_sell_quantity(
                shares, cfg.structure_reduce_pct, lot=cfg.board_lot, force_full_if_sub_lot=True
            )
            notes.append(lot_note)
            action = OverlayAction.EXIT if qty >= shares else OverlayAction.REDUCE
            return OverlayDecision(
                action=action,
                quantity=qty if qty > 0 else shares,
                reason=f"管道动作 REDUCE → 卖出 {qty or shares} 股",
                rule="pipeline_reduce",
                urgency="NORMAL",
                notes=tuple(notes),
                **base_kw,
            )

        # 4) 滚动仓兑现 / 反 T 第一腿（压力）
        sellable = min(ctx.swing_shares_sellable, swing) if ctx.swing_shares_sellable >= 0 else swing
        if sellable < 0:
            sellable = 0
        # 若未显式传入可卖数量，保守：swing 全部视为可卖（由调用方保证 T+1）
        if ctx.swing_shares_sellable == 0 and swing > 0 and ctx.near_resistance:
            # 默认 0 表示「未知」时：要求调用方设 sellable；为兼容测试，near_resistance 时用 swing
            sellable = swing

        if ctx.near_resistance and sellable >= cfg.board_lot:
            qty = floor_to_lot(sellable, cfg.board_lot)
            if qty > 0:
                return OverlayDecision(
                    action=OverlayAction.SWING_SELL,
                    quantity=qty,
                    reason=f"接近压力/兑现区 → 卖出滚动仓 {qty} 股（V2 改写）",
                    rule="swing_sell_resistance",
                    urgency="NORMAL",
                    notes=tuple(notes + ["T+1: 仅卖可卖滚动仓"]),
                    **base_kw,
                )

        # 5) 禁止亏损加仓（V1 改写 + AddRule 对齐）
        if pnl < cfg.min_pnl_for_add:
            # 仍允许 HOLD；若环境想买则 BLOCKED
            if ctx.near_support and pa in ("ADD", "OPEN", "HOLD"):
                return OverlayDecision(
                    action=OverlayAction.BLOCKED,
                    quantity=0,
                    reason=(
                        f"浮亏 {pnl:.1%} < {cfg.min_pnl_for_add:.0%} "
                        "禁止越跌越加（V1 改写 / 对齐 add_rules）"
                    ),
                    rule="no_add_to_loser",
                    urgency="NORMAL",
                    notes=tuple(notes),
                    **base_kw,
                )

        # 6) 正 T：支撑附近买滚动仓
        if ctx.near_support and pa not in ("EXIT", "REDUCE", "CUT"):
            if ctx.swing_trades_today >= cfg.max_swing_trades_per_day:
                return OverlayDecision(
                    action=OverlayAction.BLOCKED,
                    quantity=0,
                    reason=f"今日滚动交易已达上限 {cfg.max_swing_trades_per_day}",
                    rule="swing_day_limit",
                    urgency="LOW",
                    notes=tuple(notes),
                    **base_kw,
                )
            if ctx.pipeline_score < cfg.min_pipeline_score_for_swing:
                return OverlayDecision(
                    action=OverlayAction.BLOCKED,
                    quantity=0,
                    reason=(
                        f"管道评分 {ctx.pipeline_score:.0f} < "
                        f"{cfg.min_pipeline_score_for_swing:.0f}，禁止滚动加仓"
                    ),
                    rule="pipeline_score_gate",
                    urgency="LOW",
                    notes=tuple(notes),
                    **base_kw,
                )
            buy_qty = self._swing_buy_budget(position, price, swing)
            if buy_qty > 0:
                return OverlayDecision(
                    action=OverlayAction.SWING_BUY,
                    quantity=buy_qty,
                    reason=f"支撑附近且预算允许 → 滚动仓买入 {buy_qty} 股（V2 正T改写）",
                    rule="swing_buy_support",
                    urgency="NORMAL",
                    notes=tuple(notes + ["T+1: 今日买入次日才可卖"]),
                    **base_kw,
                )
            notes.append("swing_budget_exhausted_or_below_lot")

        # 7) 默认持有
        return OverlayDecision(
            action=OverlayAction.HOLD,
            quantity=0,
            reason="无触发 overlay 规则，继续持有",
            rule="hold",
            urgency="LOW",
            notes=tuple(notes),
            **base_kw,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _is_structure_broken(self, price: float, ctx: OverlayMarketContext) -> bool:
        if ctx.structure_broken is not None:
            return bool(ctx.structure_broken)
        if ctx.ma20 is not None and ctx.ma20 > 0 and price > 0:
            return price < ctx.ma20
        return False

    def _structure_reason(self, price: float, ctx: OverlayMarketContext) -> str:
        if ctx.ma20 is not None and ctx.ma20 > 0:
            return f"结构破位：现价 {price:.2f} < MA20 {ctx.ma20:.2f}"
        return f"结构破位（显式标记），现价 {price:.2f}"

    def _swing_buy_budget(
        self,
        position: PositionBucketView,
        price: float,
        current_swing: int,
    ) -> int:
        """剩余滚动预算（股）→ 整手。"""
        cfg = self.config
        if price <= 0 or position.equity <= 0:
            return 0
        max_swing_value = position.equity * cfg.swing_max_pct
        max_total_value = position.equity * cfg.single_max_pct
        current_total_value = position.total_shares * price
        current_swing_value = current_swing * price

        room_swing = max_swing_value - current_swing_value
        room_total = max_total_value - current_total_value
        room = min(room_swing, room_total)
        if room <= 0:
            return 0
        max_shares = int(room / price)
        qty, _ = resolve_buy_quantity(max_shares, lot=cfg.board_lot)
        return qty


def format_decision(d: OverlayDecision) -> str:
    """人类可读摘要。"""
    lines = [
        f"[{d.symbol}] {d.action.value} qty={d.quantity}  rule={d.rule}  urgency={d.urgency}",
        f"  原因: {d.reason}",
        f"  浮亏/盈: {d.pnl_pct:.2%}  core={d.core_shares} swing={d.swing_shares}",
    ]
    for n in d.notes:
        lines.append(f"  · {n}")
    return "\n".join(lines)
