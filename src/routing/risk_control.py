# -*- coding: utf-8 -*-
"""风控执行 — 硬约束执行（不可覆盖）。Phase 4: Alpha 衰减风控。
Phase 8: 接入 RiskState 状态机 (借鉴 RiskGuard) — HWM 追踪 / 熔断自动置位 / NaN 防御。
Phase 9: 三元裁决聚合 (借鉴 RiskGuard _aggregate) — REJECT > RESIZE > APPROVE。
Phase 9: 敞口规则 (gross/net exposure) + 策略隔离观察 (quarantine)。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Callable, Optional

from .positioning import TradeSignal
from .risk_state import RiskState
from src.utils.decimal_utils import D, safe_divide

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# 裁决枚举 (Phase 9: 借鉴 RiskGuard engine.py:_aggregate)
# ══════════════════════════════════════════════════════════════════════

class RiskVerdict(Enum):
    """单条风控规则的裁决结果。

    REJECT > RESIZE > APPROVE — 任何规则说 REJECT 则整体 REJECT。
    多个 RESIZE 取最保守（最小调整仓位）。
    """
    APPROVE = auto()  # 无违规，放行
    RESIZE = auto()   # 需缩减仓位
    REJECT = auto()   # 禁止交易


@dataclass
class _RuleResult:
    """单条风控规则的内部裁决。

    Attributes:
        verdict: 裁决结果
        violations: 违规信息列表
        adjusted_weight: 调整后的仓位（RESIZE 时提供，None 表示不限制）
    """
    verdict: RiskVerdict
    violations: list[str] = field(default_factory=list)
    adjusted_weight: float | None = None


# ══════════════════════════════════════════════════════════════════════
# 公共类型
# ══════════════════════════════════════════════════════════════════════

@dataclass
class RiskCheck:
    """风控审查结果。"""
    passed: bool
    violations: list[str] = field(default_factory=list)
    adjusted_weight: float = 0.0
    source_citations: list = field(default_factory=list)  # Phase 1: 继承引用链
    breaker_tripped: bool = False  # Phase 8: 熔断状态
    drawdown: float = 0.0  # Phase 8: 当前回撤


# ══════════════════════════════════════════════════════════════════════
# 风控引擎
# ══════════════════════════════════════════════════════════════════════

class RiskControlEngine:
    """风控执行引擎 — 带 HWM 回撤追踪状态机 + 三元裁决聚合。

    硬约束（不可覆盖）:
      - 单票最大仓位: 20%
      - 单行业最大仓位: 40%
      - 组合总敞口上限 (gross exposure)
      - 组合净敞口上限 (net exposure)
      - 单笔最大亏损: 2% (短线用 ATR 止损)
      - 组合最大回撤: 15%
      - 双创折扣: ×0.8
      - 黑天鹅熔断: 沪深300 单日 -5%
      - 流动性上限: 持仓 < 日均成交额 5%

    Phase 7 短线模式新增:
      - ATR 倍率止损 (替代固定 -2%)
      - 时间止损 (N 日不涨即离场)
      - 移动止损 (最高价回撤 N%)

    Phase 8 状态机 (借鉴 RiskGuard):
      - RiskState HWM 追踪 + 自动熔断置位
      - NaN 防御 (坏 tick 不污染状态)
      - 减仓/REDUCE/CLOSE 操作绕过熔断检查 (减仓永不拦截)
      - 审计与风控解耦 (_safe_audit)

    Phase 9 三元聚合 (借鉴 RiskGuard _aggregate):
      - 每条规则独立返回 RiskVerdict (APPROVE / RESIZE / REJECT)
      - REJECT 优先于 RESIZE 优先于 APPROVE
      - 多个 RESIZE 取最保守（最小）调整仓位
    """

    SINGLE_STOCK_CAP = Decimal("0.20")
    SINGLE_SECTOR_CAP = Decimal("0.40")
    MAX_DRAWDOWN_PCT = 0.15  # 组合最大回撤比例，与 RiskGuard 保持一致
    SINGLE_STOP_LOSS = Decimal("-0.02")
    BLACK_SWAN_THRESHOLD = Decimal("-0.05")
    # Phase 4: Alpha 衰减阈值
    ALPHA_DECAY_WARN_DAYS = 30          # Alpha 30 天未更新 → 警告
    ALPHA_CROWDED_WEIGHT_CUT = 0.5      # 拥挤时仓位减半

    def __init__(
        self,
        state: Optional[RiskState] = None,
        *,
        on_audit_error: Optional[Callable[[Exception], None]] = None,
    ):
        """初始化风控引擎。

        Args:
            state: 初始风控状态。None 则用 RiskState.initial()。
            on_audit_error: 审计写入失败回调。None 则静默（审计失败不得阻断风控）。
        """
        self._state = state if state is not None else RiskState.initial()
        self._on_audit_error = on_audit_error

    # ------------------------------------------------------------------
    # 状态访问
    # ------------------------------------------------------------------
    @property
    def state(self) -> RiskState:
        """当前风控状态快照（不可变）。"""
        return self._state

    @property
    def breaker_tripped(self) -> bool:
        return self._state.breaker_tripped

    @property
    def drawdown(self) -> float:
        return self._state.drawdown

    def register_strategy(self, strategy_id: str) -> None:
        """显式登记策略入役时间（隔离观察期从此刻算起）。"""
        self._state = self._state.register_strategy(strategy_id)

    # ------------------------------------------------------------------
    # 权益观测 & 自动熔断
    # ------------------------------------------------------------------
    def update_equity(self, equity: float) -> RiskState:
        """在下单流程之外观测一次权益。

        - 更新 HWM
        - 回撤触及 ``MAX_DRAWDOWN_PCT`` 时自动熔断置位
        - NaN 防御: 坏读数直接忽略

        返回更新后的状态。
        """
        self._observe_locked(equity)
        return self._state

    def reset_breaker(self) -> RiskState:
        """人工复盘后重置熔断，HWM 归位到当前权益。"""
        was_tripped = self._state.breaker_tripped
        self._state = self._state.reset_breaker()
        if was_tripped:
            self._safe_audit(
                "breaker_reset",
                equity=self._state.last_equity,
            )
        return self._state

    # ------------------------------------------------------------------
    # 风控审查 (Phase 9: 三元裁决聚合)
    # ------------------------------------------------------------------
    def check(
        self,
        signal: TradeSignal,
        portfolio: dict | None = None,
        market: dict | None = None,
        position_limits: dict | None = None,
    ) -> RiskCheck:
        """风控审查 — 逐规则裁决 + 三元聚合。

        Args:
            signal: 交易信号
            portfolio: 当前组合状态 {sector_pct, position_loss_pct, current_price, ...}
            market: 市场状态 {hs300_change_pct}
            position_limits: 用户偏好风控约束，覆盖类级默认值。
                             键: single_stock_cap, sector_cap, max_drawdown, stop_loss,
                                  max_gross_exposure_pct, max_net_exposure_pct,
                                  quarantine_days, quarantine_position_pct

        Phase 9 更新:
            - 每条规则返回 _RuleResult (APPROVE/RESIZE/REJECT)
            - _aggregate() 合并: REJECT > RESIZE(最保守) > APPROVE
            - 减仓/REDUCE/CLOSE 绕过熔断和回撤检查 (减仓永不拦截)
        """
        portfolio = portfolio or {}
        market = market or {}
        weight = D(signal.target_weight)

        # -- 减仓/平仓判定: 这些操作永远不应被熔断/回撤规则阻拦 --
        is_reducing = signal.action in ("REDUCE", "CLOSE")
        is_reduce_only = getattr(signal, "reduce_only", False)
        skip_risk = is_reducing or is_reduce_only

        # -- 各规则独立裁决 --
        rules: list[_RuleResult] = [
            self._check_quarantine(weight, signal, position_limits),
            self._check_single_stock_cap(weight, position_limits),
            self._check_sector_cap(weight, portfolio, position_limits),
            self._check_gross_exposure(weight, portfolio, position_limits),
            self._check_net_exposure(weight, signal, portfolio, position_limits),
            self._check_black_swan(signal, market, position_limits),
            self._check_drawdown(weight, signal, skip_risk, position_limits),
            self._check_stop_loss(weight, signal, portfolio, position_limits),
            self._check_alpha_decay(signal, portfolio),
            self._check_blacklist_rule(signal, portfolio),
            self._check_game_theory(weight, portfolio),
            self._check_manipulation(weight, signal, portfolio, position_limits),
        ]

        # -- 三元聚合 --
        return self._aggregate(rules, weight, signal)

    # ------------------------------------------------------------------
    # 三元聚合 (Phase 9: 借鉴 RiskGuard engine.py:_aggregate)
    # ------------------------------------------------------------------
    def _aggregate(
        self,
        rules: list[_RuleResult],
        initial_weight: Decimal,
        signal: TradeSignal,
    ) -> RiskCheck:
        """合并所有规则的裁决结果。

        优先级:
          - 任一 REJECT → 整体 REJECT (weight=0)
          - 多个 RESIZE → 取最保守（最小 adjusted_weight）
          - 全部 APPROVE → 放行

        借鉴 RiskGuard:
          RiskGuard 在 engine.py:_aggregate() 中使用相同的三元模式，
          但基于 RiskDecision 而非字符串匹配。
        """
        all_violations: list[str] = []
        verdict = RiskVerdict.APPROVE
        most_conservative: Decimal | None = None

        for result in rules:
            all_violations.extend(result.violations)

            if result.verdict == RiskVerdict.REJECT:
                verdict = RiskVerdict.REJECT
                # REJECT 意味着 weight=0，但继续收集违规信息用于诊断
            elif result.verdict == RiskVerdict.RESIZE and verdict != RiskVerdict.REJECT:
                verdict = RiskVerdict.RESIZE
                if result.adjusted_weight is not None:
                    rw = D(result.adjusted_weight)
                    most_conservative = (
                        rw if most_conservative is None
                        else min(most_conservative, rw)
                    )

        # 应用最保守的 RESIZE
        weight = initial_weight
        if verdict == RiskVerdict.REJECT:
            weight = D("0")
        elif verdict == RiskVerdict.RESIZE and most_conservative is not None:
            weight = min(weight, most_conservative)

        return RiskCheck(
            passed=verdict != RiskVerdict.REJECT,
            violations=all_violations,
            adjusted_weight=max(0.0, float(weight)),
            source_citations=signal.source_citations,
            breaker_tripped=self._state.breaker_tripped,
            drawdown=self._state.drawdown,
        )

    # ------------------------------------------------------------------
    # 规则 1: 策略隔离观察 (Phase 9 新增)
    # ------------------------------------------------------------------
    def _check_quarantine(
        self,
        weight: Decimal,
        signal: TradeSignal,
        position_limits: dict | None,
    ) -> _RuleResult:
        """新策略/新标的隔离观察期仓位限制。

        借鉴 RiskGuard quarantine.py:
          策略入役后隔离期（默认90天）内适用更严格仓位上限（默认1%）。
          隔离期内减仓永远放行。
        """
        quarantine_days = (position_limits or {}).get("quarantine_days", 0)
        if quarantine_days <= 0:
            return _RuleResult(RiskVerdict.APPROVE, [])

        quarantine_pct = (position_limits or {}).get("quarantine_position_pct", 0.01)
        strategy_id = signal.symbol  # 以标的代码作为策略ID代理

        age = self._state.strategy_age_days(strategy_id)
        if age is None:
            # 首次交易 → 自动登记入役时间
            self._state = self._state.register_strategy(strategy_id)
            age = 0.0

        if age < quarantine_days and weight > D(str(quarantine_pct)):
            reduced = min(weight, D(str(quarantine_pct)))
            return _RuleResult(
                RiskVerdict.RESIZE,
                [
                    f"隔离期: {age:.0f}d < {quarantine_days}d, "
                    f"仓位 {float(weight):.1%} → {quarantine_pct:.1%}"
                ],
                float(reduced),
            )

        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 规则 2: 单票仓位上限
    # ------------------------------------------------------------------
    @staticmethod
    def _check_single_stock_cap(
        weight: Decimal,
        position_limits: dict | None,
    ) -> _RuleResult:
        cap = D(str((position_limits or {}).get("single_stock_cap", 0.20)))
        if weight > cap:
            return _RuleResult(
                RiskVerdict.RESIZE,
                [f"单票超限: {float(weight):.1%} > {float(cap):.0%}"],
                float(min(weight, cap)),
            )
        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 规则 3: 行业仓位上限
    # ------------------------------------------------------------------
    @staticmethod
    def _check_sector_cap(
        weight: Decimal,
        portfolio: dict,
        position_limits: dict | None,
    ) -> _RuleResult:
        cap = D(str((position_limits or {}).get("sector_cap", 0.40)))
        sector_pct = D(portfolio.get("sector_pct", 0))
        if sector_pct + weight > cap:
            allowed = max(D("0"), cap - sector_pct)
            return _RuleResult(
                RiskVerdict.RESIZE,
                [f"行业超限: {float(sector_pct + weight):.1%} > {float(cap):.0%}"],
                float(allowed),
            )
        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 规则 4: 组合总敞口上限 (Phase 9 新增，借鉴 RiskGuard exposure.py)
    # ------------------------------------------------------------------
    @staticmethod
    def _check_gross_exposure(
        weight: Decimal,
        portfolio: dict,
        position_limits: dict | None,
    ) -> _RuleResult:
        """组合总敞口 = 所有多头绝对值之和。
        GrossExposureLimit 管杠杆——多空对冲组合 gross 可能很大但 net 接近 0。
        """
        max_gross = (position_limits or {}).get("max_gross_exposure_pct")
        if max_gross is None:
            return _RuleResult(RiskVerdict.APPROVE, [])
        max_gross_d = D(str(max_gross))
        current_gross = D(str(portfolio.get("current_gross_exposure", 0.0)))
        projected = current_gross + weight
        if projected > max_gross_d:
            allowed = max(D("0"), max_gross_d - current_gross)
            return _RuleResult(
                RiskVerdict.RESIZE,
                [f"总敞口超限: {float(projected):.1%} > {float(max_gross_d):.0%}"],
                float(allowed),
            )
        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 规则 5: 组合净敞口上限 (Phase 9 新增，借鉴 RiskGuard exposure.py)
    # ------------------------------------------------------------------
    @staticmethod
    def _check_net_exposure(
        weight: Decimal,
        signal: TradeSignal,
        portfolio: dict,
        position_limits: dict | None,
    ) -> _RuleResult:
        """组合净敞口 = 多头市值 - 空头市值。
        NetExposureLimit 管方向性风险。

        RiskGuard 关键原则: 使 |净敞口| 变小的单永远放行。
        """
        max_net = (position_limits or {}).get("max_net_exposure_pct")
        if max_net is None:
            return _RuleResult(RiskVerdict.APPROVE, [])
        max_net_d = D(str(max_net))
        current_net = D(str(portfolio.get("current_net_exposure", 0.0)))
        order_sign = D("1") if signal.action in ("OPEN", "ADD") else D("-1")
        projected = current_net + order_sign * weight

        # 使净敞口变小的单永远放行
        if abs(float(projected)) <= abs(float(current_net)):
            return _RuleResult(RiskVerdict.APPROVE, [])

        if abs(float(projected)) > float(max_net_d):
            allowed = (
                max(D("0"), max_net_d - current_net) if order_sign > D("0")
                else D("0")
            )
            return _RuleResult(
                RiskVerdict.RESIZE,
                [f"净敞口超限: {float(projected):.1%} > {float(max_net_d):.0%}"],
                float(allowed),
            )
        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 规则 6: 黑天鹅熔断
    # ------------------------------------------------------------------
    def _check_black_swan(
        self,
        signal: TradeSignal,
        market: dict,
        position_limits: dict | None,
    ) -> _RuleResult:
        threshold = D(str((position_limits or {}).get("black_swan_threshold_pct", -0.05)))
        market_drop = D(market.get("hs300_change_pct", 0))
        if market_drop <= threshold:
            if signal.action in ("OPEN", "ADD"):
                return _RuleResult(
                    RiskVerdict.REJECT,
                    ["黑天鹅熔断: T+1 禁开新仓"],
                )
        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 规则 7: 组合回撤熔断 (Phase 8: 从 RiskState HWM 读取)
    # ------------------------------------------------------------------
    def _check_drawdown(
        self,
        weight: Decimal,
        signal: TradeSignal,
        skip_risk: bool,
        position_limits: dict | None,
    ) -> _RuleResult:
        """回撤熔断 — 减仓永不拦截。"""
        if skip_risk:
            if self._state.breaker_tripped:
                logger.info(
                    "熔断中减仓放行: %s %s (回撤 %.1f%%)",
                    signal.symbol, signal.action, self._state.drawdown * 100,
                )
            return _RuleResult(RiskVerdict.APPROVE, [])

        max_dd = (position_limits or {}).get("max_drawdown_pct", self.MAX_DRAWDOWN_PCT)
        state_drawdown = self._state.drawdown

        if state_drawdown >= max_dd:
            return _RuleResult(
                RiskVerdict.REJECT,
                [f"组合回撤熔断: {state_drawdown:.1%} >= {max_dd:.1%} "
                 f"(HWM={self._state.high_water_mark:.0f}, "
                 f"当前权益={self._state.last_equity:.0f})"],
            )

        if self._state.breaker_tripped:
            return _RuleResult(
                RiskVerdict.REJECT,
                [f"熔断中: {self._state.trip_reason} (回撤 {state_drawdown:.1%})"],
            )

        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 规则 8: 止损 (ATR / 固定 / 时间 / 移动)
    # ------------------------------------------------------------------
    @staticmethod
    def _check_stop_loss(
        weight: Decimal,
        signal: TradeSignal,
        portfolio: dict,
        position_limits: dict | None,
    ) -> _RuleResult:
        """止损检查 — 包括 ATR 止损、固定百分比止损、时间止损、移动止损。"""
        violations: list[str] = []
        stop_loss_pct = (position_limits or {}).get("stop_loss", -0.02)

        # ATR 止损
        if signal.suggested_stop > 0 and portfolio.get("current_price", 0) > 0:
            current_price = D(portfolio.get("current_price", 0))
            stop_price = D(signal.suggested_stop)
            if current_price <= stop_price:
                violations.append(
                    f"ATR止损触发: 现价{float(current_price):.2f} <= 止损价{float(stop_price):.2f}"
                )
                return _RuleResult(RiskVerdict.REJECT, violations)

        # 固定百分比止损
        position_loss = D(portfolio.get("position_loss_pct", 0))
        if position_loss <= D(str(stop_loss_pct)):
            violations.append(
                f"单笔止损: {float(position_loss):.1%} 触及 {stop_loss_pct:.0%}"
            )
            return _RuleResult(RiskVerdict.REJECT, violations)

        # 时间止损
        holding_days = portfolio.get("holding_days", 0) or 0
        if signal.time_stop_days > 0 and holding_days >= signal.time_stop_days:
            position_pnl = D(portfolio.get("position_pnl_pct", 0))
            if position_pnl <= D("0"):
                violations.append(
                    f"时间止损: 持有{holding_days}天 >= {signal.time_stop_days}天且未盈利"
                )
                return _RuleResult(RiskVerdict.REJECT, violations)

        # 移动止损
        if signal.suggested_stop > 0 and getattr(signal, "atr_stop", 0) > 0:
            peak_price = D(portfolio.get("peak_price", 0) or 0)
            current_px = D(portfolio.get("current_price", 0) or 0)
            if peak_price > D("0") and current_px > D("0"):
                drawdown_from_peak = (current_px - peak_price) / peak_price
                trailing_pct = D(str((position_limits or {}).get("trailing_stop_pct", -0.03)))
                if drawdown_from_peak <= trailing_pct:
                    violations.append(
                        f"移动止损: 从高点{float(peak_price):.2f}回撤{float(drawdown_from_peak):.1%}"
                    )
                    return _RuleResult(RiskVerdict.REJECT, violations)

        if violations:
            return _RuleResult(RiskVerdict.REJECT, violations)
        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 规则 9: Alpha 衰减风控
    # ------------------------------------------------------------------
    def _check_alpha_decay(
        self,
        signal: TradeSignal,
        portfolio: dict,
    ) -> _RuleResult:
        """Phase 4: Alpha 衰减风控检查。

        检查项:
          1. Alpha 衰减速度过快 → 减仓提醒
          2. 叙事阶段迁移 → 调整建议
          3. 讨论量暴涨 + 逻辑无更新 → 拥挤警告
        """
        violations: list[str] = []
        alpha_tracker = portfolio.get("alpha_tracker", {})

        decay_velocity = alpha_tracker.get("decay_velocity", 0.0)
        if decay_velocity > 1.0:
            violations.append(
                f"ALPHA_DECAY: Alpha 快速衰减 ({decay_velocity:.1f}/天), 建议减仓"
            )
        elif decay_velocity > 0.3:
            violations.append(
                f"ALPHA_AGING: Alpha 正在衰减 ({decay_velocity:.1f}/天)"
            )

        days_since = alpha_tracker.get("days_since_detection", 0)
        if days_since > self.ALPHA_DECAY_WARN_DAYS:
            violations.append(
                f"ALPHA_STALE: Alpha 信号 {days_since} 天未更新，可能已失效"
            )

        is_crowded = alpha_tracker.get("is_crowded", False)
        if is_crowded:
            violations.append(
                "ALPHA_CROWDED: Alpha 已被拥挤挤出，建议清仓或大幅减仓"
            )

        narrative_stage = alpha_tracker.get("narrative_stage", "")
        if narrative_stage in ("consensus", "crowded"):
            violations.append(
                f"ALPHA_STAGE_SHIFT: 叙事进入 {narrative_stage} 阶段, "
                "Alpha 空间显著收窄"
            )
            if narrative_stage == "crowded":
                violations.append("ALPHA_EXIT: 叙事拥挤，建议清仓离场")

        if violations:
            logger.info(
                "Alpha decay risk for %s: %s",
                signal.symbol,
                "; ".join(violations),
            )

        # Alpha 衰减中的 CROWDED/EXIT 触发 REJECT，其他触发 RESIZE
        if any("清仓" in v for v in violations) or any("EXIT" in v for v in violations):
            return _RuleResult(RiskVerdict.REJECT, violations)
        if violations:
            return _RuleResult(RiskVerdict.RESIZE, violations, float(D("0.5") * D(signal.target_weight)))
        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 规则 10: 黑名单
    # ------------------------------------------------------------------
    def _check_blacklist_rule(
        self,
        signal: TradeSignal,
        portfolio: dict,
    ) -> _RuleResult:
        """黑名单检查 — 委托给静态方法。"""
        violations = self._check_blacklist(
            signal.symbol, signal.name,
            quote_data=signal.extra or {},
        )
        if violations:
            return _RuleResult(RiskVerdict.REJECT, violations)
        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 规则 11: 博弈论风险约束
    # ------------------------------------------------------------------
    @staticmethod
    def _check_game_theory(
        weight: Decimal,
        portfolio: dict,
    ) -> _RuleResult:
        """Phase 6: 博弈论风险约束。"""
        gt_risks = portfolio.get("game_theory_risks", [])
        if not gt_risks:
            return _RuleResult(RiskVerdict.APPROVE, [])

        critical_gt = {
            "seat_distribution_sell",
            "sector_crowded",
            "leverage_fear",
            "hot_money_dominant_large_cap_mismatch",
        }

        violations: list[str] = list(gt_risks)

        if any("seat_distribution_sell" in v for v in gt_risks):
            return _RuleResult(RiskVerdict.REJECT, violations)

        if any(any(k in v for k in critical_gt) for v in gt_risks):
            return _RuleResult(
                RiskVerdict.RESIZE, violations,
                float(weight * D("0.5")),
            )

        return _RuleResult(RiskVerdict.RESIZE, violations, float(weight))

    # ------------------------------------------------------------------
    # 规则 12: 操纵感知止损
    # ------------------------------------------------------------------
    @staticmethod
    def _check_manipulation(
        weight: Decimal,
        signal: TradeSignal,
        portfolio: dict,
        position_limits: dict | None,
    ) -> _RuleResult:
        """Phase 11: 操纵感知止损策略。"""
        manip_pattern = portfolio.get("manipulation_pattern", "")
        manip_risk = float(portfolio.get("manipulation_risk_score", 0) or 0)
        if manip_risk <= 30 or not manip_pattern:
            return _RuleResult(RiskVerdict.APPROVE, [])

        current_px = D(portfolio.get("current_price", 0) or 0)
        day_avg_price = D(portfolio.get("day_avg_price", 0) or 0)
        violations: list[str] = []

        if manip_pattern in ("lure_bull_dump", "news_distribution"):
            if current_px > D("0") and day_avg_price > D("0") and current_px <= day_avg_price:
                violations.append(
                    f"操纵感知止损: {manip_pattern} — 跌破均价{float(day_avg_price):.2f}，快速止损"
                )
                return _RuleResult(RiskVerdict.REJECT, violations)
        elif manip_pattern == "shakeout":
            if position_limits:
                wider_stop = D(str(position_limits.get("stop_loss", -0.02))) - D("0.02")
                position_limits["stop_loss"] = float(wider_stop)
        elif manip_pattern == "fishing_line":
            violations.append("操纵感知止损: fishing_line 钓鱼线 — 最高风险，立即止损")
            return _RuleResult(RiskVerdict.REJECT, violations)
        elif manip_pattern in ("closing_pump", "closing_dump"):
            violations.append(
                f"操纵感知止损: {manip_pattern} — 次日开盘15分钟未走强建议止损"
            )
        elif manip_pattern == "wash_trade_pump":
            violations.append("操纵感知止损: wash_trade_pump — 对倒拉升，缩量即逃")

        if violations:
            return _RuleResult(RiskVerdict.RESIZE, violations, 0.0)
        return _RuleResult(RiskVerdict.APPROVE, [])

    # ------------------------------------------------------------------
    # 内部方法: 状态观测 / 审计解耦
    # ------------------------------------------------------------------
    def _observe_locked(self, equity: float) -> None:
        """观测权益并按需触发熔断（调用方需自行管理并发安全）。

        借鉴 RiskGuard engine.py:_observe_locked() 设计:
            1. NaN 防御 (observe_equity 内置)
            2. 更新 HWM
            3. 回撤触及阈值 → 自动熔断置位
            4. 审计事件写入 (_safe_audit 包裹)
        """
        was_tripped = self._state.breaker_tripped
        new_state = self._state.observe_equity(equity)

        # 自动熔断: 回撤达到或超过阈值
        if (
            not new_state.breaker_tripped
            and new_state.high_water_mark > 0
            and new_state.drawdown >= self.MAX_DRAWDOWN_PCT
        ):
            reason = (
                f"drawdown {new_state.drawdown:.2%} >= limit "
                f"{self.MAX_DRAWDOWN_PCT:.2%} "
                f"(HWM={new_state.high_water_mark:.0f}, "
                f"equity={new_state.last_equity:.0f})"
            )
            new_state = new_state.trip(reason)

        self._state = new_state

        # 新触发熔断 → 审计记录
        if not was_tripped and new_state.breaker_tripped:
            self._safe_audit(
                "breaker_trip",
                reason=new_state.trip_reason,
                equity=new_state.last_equity,
                high_water_mark=new_state.high_water_mark,
                drawdown=new_state.drawdown,
            )

    def _safe_audit(self, event_type: str, **detail: object) -> None:
        """审计写入。**绝不让审计失败阻断风控裁决**。

        借鉴 RiskGuard: 审计是次要职责——磁盘满、IO 异常等绝不能
        把 allow/deny 的主判决带崩。失败时转交 on_audit_error 回调
        （缺省静默），风控裁决照常返回。
        """
        try:
            logger.info(
                "RISK_AUDIT | %s | %s",
                event_type,
                ", ".join(f"{k}={v}" for k, v in detail.items()),
            )
        except Exception as e:
            if self._on_audit_error is not None:
                try:
                    self._on_audit_error(e)
                except Exception:
                    pass  # 回调自身也不能炸

    # ------------------------------------------------------------------
    # Auto-blacklist
    # ------------------------------------------------------------------

    # Static blacklist (manually maintained)
    STATIC_BLACKLIST: set[str] = set()  # e.g., known fraud, delisting risk

    @classmethod
    def add_to_blacklist(cls, symbol: str) -> None:
        """Manually add a symbol to the static blacklist."""
        cls.STATIC_BLACKLIST.add(symbol)

    @classmethod
    def remove_from_blacklist(cls, symbol: str) -> None:
        """Remove a symbol from the static blacklist."""
        cls.STATIC_BLACKLIST.discard(symbol)

    @classmethod
    def get_blacklist(cls) -> set[str]:
        """Get the full blacklist (static + dynamic)."""
        return cls.STATIC_BLACKLIST.copy()

    @staticmethod
    def _check_blacklist(symbol: str, name: str = "", quote_data: dict | None = None) -> list[str]:
        """Auto-detect and blacklist high-risk stocks.

        Checks:
          - ST / *ST prefix in name
          - Static blacklist
          - Daily volume < 50M RMB (low liquidity)
          - Continuous limit-down (consecutive -10%)
          - Delisting warning signals
        """
        violations = []

        # Static blacklist
        if symbol in RiskControlEngine.STATIC_BLACKLIST:
            violations.append(f"黑名单: {symbol} 在静态黑名单中")
            return violations

        # ST / *ST check
        if name and ("ST" in name.upper() or "*ST" in name.upper()):
            violations.append(f"黑名单: {name} 为ST/*ST股票")
            return violations

        if quote_data:
            # Low liquidity — prefer amount field; fall back to volume×price
            amount = quote_data.get("amount", 0) or quote_data.get("turnover", 0) or 0
            if amount > 0:
                turnover = amount
            else:
                volume = quote_data.get("volume", 0) or 0
                price = quote_data.get("price", 0) or 0
                # volume from Tencent is in 手 (lots of 100 shares)
                turnover = volume * 100 * price
            if turnover > 0 and turnover < 50_000_000:  # < 50M daily
                violations.append(f"低流动性: 日成交额 {turnover/1e4:.0f}万 < 5000万")

            # Limit-down streak
            limit_down_streak = quote_data.get("limit_down_streak", 0) or 0
            if limit_down_streak >= 2:
                violations.append(f"连续跌停: {limit_down_streak}天")

            # Delisting risk markers
            if quote_data.get("is_delisting_risk"):
                violations.append("退市风险警示")
            if quote_data.get("audit_opinion") == "non_standard":
                violations.append("审计意见非标")

        return violations
