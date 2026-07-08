# -*- coding: utf-8 -*-
"""风控执行 — 硬约束执行（不可覆盖）。Phase 4: Alpha 衰减风控。
Phase 8: 接入 RiskState 状态机 (借鉴 RiskGuard) — HWM 追踪 / 熔断自动置位 / NaN 防御。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

from .positioning import TradeSignal
from .risk_state import RiskState
from src.utils.decimal_utils import D, safe_divide

logger = logging.getLogger(__name__)


@dataclass
class RiskCheck:
    """风控审查结果。"""
    passed: bool
    violations: list[str] = field(default_factory=list)
    adjusted_weight: float = 0.0
    source_citations: list = field(default_factory=list)  # Phase 1: 继承引用链
    breaker_tripped: bool = False  # Phase 8: 熔断状态
    drawdown: float = 0.0  # Phase 8: 当前回撤


class RiskControlEngine:
    """风控执行引擎 — 带 HWM 回撤追踪状态机。

    硬约束（不可覆盖）:
      - 单票最大仓位: 20%
      - 单行业最大仓位: 40%
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
    """

    SINGLE_STOCK_CAP = Decimal("0.20")
    SINGLE_SECTOR_CAP = Decimal("0.40")
    MAX_DRAWDOWN_PCT = 0.15  # Phase 8: 改名为正数比例，与 RiskGuard 保持一致
    MAX_DRAWDOWN = Decimal("-0.15")  # 保留旧名称兼容
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
    # 风控审查
    # ------------------------------------------------------------------
    def check(
        self,
        signal: TradeSignal,
        portfolio: dict | None = None,
        market: dict | None = None,
        position_limits: dict | None = None,
    ) -> RiskCheck:
        """风控审查。返回调整后的仓位。

        Args:
            signal: 交易信号
            portfolio: 当前组合状态 {sector_pct, position_loss_pct, current_price, ...}
            market: 市场状态 {hs300_change_pct}
            position_limits: 用户偏好风控约束，覆盖类级默认值。
                             键: single_stock_cap, sector_cap, max_drawdown, stop_loss

        Phase 8 更新:
            - drawdown 从 self._state 读取 (HWM 追踪)，不再依赖 portfolio dict
            - 减仓/REDUCE/CLOSE 绕过熔断和回撤检查 (减仓永不拦截)
        """
        violations: list[str] = []
        weight = D(signal.target_weight)

        # -- 减仓/平仓判定: 这些操作永远不应被熔断/回撤规则阻拦 --
        is_reducing = signal.action in ("REDUCE", "CLOSE")
        # 同时也检查 reduce_only 标记 (新 LEAN 协议)
        is_reduce_only = getattr(signal, "reduce_only", False)

        # 用户偏好覆盖（类常量已是 Decimal，position_limits 中的值需 D() 转换）
        _single_stock_cap = self.SINGLE_STOCK_CAP
        _sector_cap = self.SINGLE_SECTOR_CAP
        _max_drawdown = self.MAX_DRAWDOWN
        _stop_loss = self.SINGLE_STOP_LOSS
        if position_limits:
            _single_stock_cap = D(position_limits.get("single_stock_cap", float(_single_stock_cap)))
            _sector_cap = D(position_limits.get("sector_cap", float(_sector_cap)))
            _max_drawdown = D(position_limits.get("max_drawdown", float(_max_drawdown)))
            _stop_loss = D(position_limits.get("stop_loss", float(_stop_loss)))

        # 单票上限
        if weight > _single_stock_cap:
            violations.append(f"单票超限: {float(weight):.1%} > {float(_single_stock_cap):.0%}")
            weight = min(weight, _single_stock_cap)

        # 行业上限
        sector_pct = D((portfolio or {}).get("sector_pct", 0))
        if sector_pct + weight > _sector_cap:
            violations.append(f"行业超限: {float(sector_pct + weight):.1%} > {float(_sector_cap):.0%}")
            weight = min(weight, _sector_cap - sector_pct)

        # 黑天鹅熔断
        market_drop = D((market or {}).get("hs300_change_pct", 0))
        if market_drop <= self.BLACK_SWAN_THRESHOLD:
            violations.append("黑天鹅熔断: T+1 禁开新仓")
            if signal.action in ("OPEN", "ADD"):
                weight = D("0")

        # -- 组合回撤熔断 (Phase 8: 从 RiskState HWM 读取) --
        state_drawdown = self._state.drawdown
        if not is_reducing and not is_reduce_only:
            # 减仓永不拦截 — 熔断后必须能平仓，否则风险无法收敛
            max_dd_pct = abs(float(_max_drawdown))
            if state_drawdown >= max_dd_pct:
                violations.append(
                    f"组合回撤熔断: {state_drawdown:.1%} >= {max_dd_pct:.1%} "
                    f"(HWM={self._state.high_water_mark:.0f}, "
                    f"当前权益={self._state.last_equity:.0f})"
                )
                weight = min(weight, D("0"))
            elif self._state.breaker_tripped:
                violations.append(
                    f"熔断中: {self._state.trip_reason} (回撤 {state_drawdown:.1%})"
                )
                weight = min(weight, D("0"))
        elif self._state.breaker_tripped:
            # 减仓操作在熔断期间依然放行，但记录日志
            logger.info(
                "熔断中减仓放行: %s %s (回撤 %.1f%%)",
                signal.symbol, signal.action, state_drawdown * 100,
            )

        # 单笔止损 (支持 ATR/时间/移动止损)
        position_loss = D((portfolio or {}).get("position_loss_pct", 0))
        if signal.suggested_stop > 0 and (portfolio or {}).get("current_price", 0) > 0:
            current_price = D((portfolio or {}).get("current_price", 0))
            stop_price = D(signal.suggested_stop)
            if current_price <= stop_price:
                violations.append(
                    f"ATR止损触发: 现价{float(current_price):.2f} <= 止损价{float(stop_price):.2f}"
                )
                weight = D("0")
        elif position_loss <= _stop_loss:
            violations.append(f"单笔止损: {float(position_loss):.1%} 触及 {float(_stop_loss):.0%}")
            weight = D("0")  # 强制平仓

        # 时间止损 (短线模式特有)
        holding_days = (portfolio or {}).get("holding_days", 0) or 0
        if signal.time_stop_days > 0 and holding_days >= signal.time_stop_days:
            position_pnl = D((portfolio or {}).get("position_pnl_pct", 0))
            if position_pnl <= D("0"):
                violations.append(
                    f"时间止损: 持有{holding_days}天 >= {signal.time_stop_days}天且未盈利"
                )
                weight = min(weight, D("0"))

        # 移动止损 (短线模式: 从最高点回撤 N%)
        if signal.suggested_stop > 0 and getattr(signal, "atr_stop", 0) > 0:
            peak_price = D((portfolio or {}).get("peak_price", 0) or 0)
            current_px = D((portfolio or {}).get("current_price", 0) or 0)
            if peak_price > D("0") and current_px > D("0"):
                drawdown_from_peak = (current_px - peak_price) / peak_price
                trailing_pct = D("-0.03")  # default -3%
                if position_limits:
                    trailing_pct = D(position_limits.get("trailing_stop_pct", float(trailing_pct)))
                if drawdown_from_peak <= trailing_pct:
                    violations.append(
                        f"移动止损: 从高点{float(peak_price):.2f}回撤{float(drawdown_from_peak):.1%}"
                    )
                    weight = min(weight, D("0"))

        # Phase 4: Alpha 衰减风控检查
        alpha_violations = self._check_alpha_decay(signal, portfolio or {})
        violations.extend(alpha_violations)
        if any("清仓" in v for v in alpha_violations):
            weight = min(weight, D("0"))

        # Auto-blacklist check
        blacklist_violations = self._check_blacklist(signal.symbol, signal.name, quote_data=signal.extra or {})
        violations.extend(blacklist_violations)
        if any("黑名单" in v for v in blacklist_violations):
            weight = D("0")

        # Phase 6: 博弈论风险约束
        gt_risks = (portfolio or {}).get("game_theory_risks", [])
        if gt_risks:
            violations.extend(gt_risks)
            critical_gt = {
                "seat_distribution_sell",
                "sector_crowded",
                "leverage_fear",
                "hot_money_dominant_large_cap_mismatch",
            }
            if any(any(k in v for k in critical_gt) for v in gt_risks):
                weight = weight * D("0.5")
            if any("seat_distribution_sell" in v for v in gt_risks):
                weight = D("0")

        return RiskCheck(
            passed=len([v for v in violations if "熔断" in v or "止损" in v or "黑名单" in v]) == 0,
            violations=violations,
            adjusted_weight=max(0.0, float(weight)),
            source_citations=signal.source_citations,  # Phase 1: 继承引用链
            breaker_tripped=self._state.breaker_tripped,  # Phase 8
            drawdown=self._state.drawdown,  # Phase 8
        )

    # ------------------------------------------------------------------
    # 内部方法: 状态观测 / 审计解耦 / Alpha 衰减
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

    def _check_alpha_decay(
        self,
        signal: TradeSignal,
        portfolio: dict,
    ) -> list[str]:
        """Phase 4: Alpha 衰减风控检查。

        检查项:
          1. Alpha 衰减速度过快 → 减仓提醒
          2. 叙事阶段迁移 → 调整建议
          3. 讨论量暴涨 + 逻辑无更新 → 拥挤警告

        Returns:
            violations list (可能包含 ALPHA_DECAY / ALPHA_CROWDED 标记)
        """
        violations: list[str] = []

        # 从 portfolio 中获取 Alpha 追踪信息
        alpha_tracker = portfolio.get("alpha_tracker", {})

        # 1. Alpha 衰减速度检查
        decay_velocity = alpha_tracker.get("decay_velocity", 0.0)
        if decay_velocity > 1.0:
            violations.append(
                f"ALPHA_DECAY: Alpha 快速衰减 ({decay_velocity:.1f}/天), 建议减仓"
            )
        elif decay_velocity > 0.3:
            violations.append(
                f"ALPHA_AGING: Alpha 正在衰减 ({decay_velocity:.1f}/天)"
            )

        # 2. Alpha 衰减天数检查
        days_since = alpha_tracker.get("days_since_detection", 0)
        if days_since > self.ALPHA_DECAY_WARN_DAYS:
            violations.append(
                f"ALPHA_STALE: Alpha 信号 {days_since} 天未更新，可能已失效"
            )

        # 3. 拥挤检查
        is_crowded = alpha_tracker.get("is_crowded", False)
        if is_crowded:
            violations.append(
                "ALPHA_CROWDED: Alpha 已被拥挤挤出，建议清仓或大幅减仓"
            )

        # 4. 叙事阶段迁移检查
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

        return violations

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
            # Low liquidity
            volume = quote_data.get("volume", 0) or 0
            price = quote_data.get("price", 0) or 0
            turnover = volume * price  # rough turnover in RMB
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

