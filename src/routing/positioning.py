# -*- coding: utf-8 -*-
"""仓位调度 — 信号→仓位映射。Phase 4: Alpha 时序注入。Phase 5: 凯利公式仓位管理。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.kelly.base import Sizer

from .signal import Direction, PortfolioTarget, Signal, signal_from_verdict, target_from_signal
from .verdict import Verdict
from src.utils.decimal_utils import D, safe_divide

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """交易信号。

    .. deprecated::
       Use ``Signal`` + ``PortfolioTarget`` from :mod:`src.routing.signal` instead.
       ``Signal`` separates the prediction (direction/confidence/source) from the
       position-sizing decision (``PortfolioTarget``), matching the LEAN Insight
       pattern.  This class remains for backward compatibility and will be removed
       in a future release.
    """
    symbol: str
    action: str            # OPEN / ADD / HOLD / REDUCE / CLOSE
    target_weight: float   # 目标仓位占比 (0.0 - 1.0)
    is_core: bool = False  # 是否核心仓操作
    limit: float = 0.0     # 风控施加的仓位上限
    source_citations: list = field(default_factory=list)  # Phase 1: 继承引用链
    confidence: float = 0.5  # Phase 1: 信号信心度
    alpha_timing: str = ""  # Phase 4: Alpha 时序提示 (叙事阶段 + 操作提示)
    executive_risk: bool = False  # V4: 高管风险标记
    # Phase 5: 凯利公式
    sizing_method: str = ""       # "kelly" / "linear_fallback" / "negative_expectation"
    kelly_f: float = 0.0          # 原始凯利 f*
    kelly_params_source: str = ""  # 凯利参数来源说明
    name: str = ""                # 股票名称 (风控黑名单/流动性检查)
    extra: dict = field(default_factory=dict)  # 原始行情数据 (风控黑名单检查)
    # Phase 7: 短线/波段入场出场时机
    entry_zone_low: float = 0.0   # 入场区间下限
    entry_zone_high: float = 0.0  # 入场区间上限
    exit_zone_low: float = 0.0    # 出场区间下限
    exit_zone_high: float = 0.0   # 出场区间上限
    suggested_stop: float = 0.0   # 建议止损价 (ATR 或固定百分比)
    time_stop_days: int = 0       # 时间止损天数 (短线 3-7, 长线 60-180)
    atr_stop: float = 0.0         # ATR 止损价
    target_1: float = 0.0         # 第一止盈目标位
    target_2: float = 0.0         # 第二止盈目标位


class PositioningEngine:
    """仓位调度引擎。

    信号映射:
      - score ≥ 75 → 建仓/加仓
      - score 50-74 → 持有/观望
      - score 35-49 → 减仓
      - score < 35  → 清仓/回避

    Phase 5: 凯利公式仓位管理。
      - 热启动 (n≥5): target = kelly_fraction × f*, f* = (b×p - q)/b
      - 冷启动 (n<5): 回退线性公式 base = (score - 50) / 50 × macro_cap
      - 负期望 (f*≤0): target = 0，不建仓

    P0-3: 单笔风险预算反推仓位。
      - 与乘数链结果取 min: max_weight = (equity × risk_budget_pct) / (entry − stop)
        归一化后 equity 约去 → risk_budget_pct × entry / (entry − stop)。
      - 止损位须在建仓前已知（T+1 前置）；suggested_stop 缺失时回退现有逻辑。
    """

    DEFAULT_RISK_BUDGET_PCT = 0.02  # 单笔风险预算 = 权益的 2%

    def __init__(self, kelly_sizer: "Sizer | None" = None):
        """初始化仓位调度引擎。

        Args:
            kelly_sizer: Sizer 实例 (KellyPositionSizer / VolatilityTargetSizer 等)。
                         None 时仅使用线性公式。
        """
        self._kelly_sizer = kelly_sizer

    @property
    def has_kelly(self) -> bool:
        return self._kelly_sizer is not None

    def generate_signal(
        self,
        verdict: Verdict,
        macro_cap: float = 0.80,
        is_core: bool = False,
        is_gem: bool = False,
        position_limits: Optional[dict] = None,
        risk_multiplier: float = 1.0,
        name: str = "",
        extra: Optional[dict] = None,
        timing_result=None,  # Phase 7: EntryExitEngine.TimingResult
        suggested_stop: float = 0.0,  # P0-3: 直接建议止损价（timing_result 缺失时用于 risk-budget sizing）
        manipulation_risk: float = 0.0,  # Phase 11: 操纵风险评分 0-100
        portfolio_value: float = 0.0,  # P0-3: 组合权益（risk-budget sizing）
        entry_price: float = 0.0,      # P0-3: 入场价（缺省用 extra.price）
    ) -> TradeSignal:
        """生成交易信号。

        .. deprecated::
           Use :meth:`generate_signal_from_verdict` which returns a
           :class:`Signal` (prediction) and then call :meth:`signal_to_target`
           to obtain a :class:`PortfolioTarget` (execution).  This method
           returns the old monolithic ``TradeSignal`` and will be removed in a
           future release.

        Args:
            verdict: 综合裁决结果
            macro_cap: 宏观仓位上限 (0.0-1.0)
            is_core: 是否核心仓 (阻止 REDUCE/CLOSE)
            is_gem: 是否双创 (创业板/科创板折扣)
            position_limits: 用户偏好仓位约束 {"single_stock_cap": ..., "kelly_fraction": ...}
            risk_multiplier: 风险偏好仓位乘数 (conservative=0.7, balanced=1.0, aggressive=1.2)
            timing_result: Phase 7 入场/出场时机结果 (仅短线/波段模式)
            suggested_stop: P0-3 直接建议止损价（全量路径无 timing_result 时传入，
                供 risk-budget sizing 反推仓位上限；缺失时回退乘数链，不报错）
            portfolio_value: P0-3 组合权益（risk-budget sizing 公式 equity）
            entry_price: P0-3 入场价（缺省回退 extra.price/close）
        """
        score = verdict.score
        action = self._score_to_action(score)
        symbol = verdict.symbol

        # 入参 Decimal 化 — 所有算账在 Decimal 域内完成
        macro_cap_d = D(macro_cap)
        risk_mult_d = D(risk_multiplier)

        # Phase 5: 凯利公式仓位管理
        kelly_fraction = None
        if position_limits:
            kelly_fraction = position_limits.get("kelly_fraction")

        if self._kelly_sizer is not None:
            target_d, sizing_method, kelly_f, sizing_source = self._kelly_sizing(
                symbol, score, macro_cap, position_limits, kelly_fraction,
            )
        else:
            # 无 Kelly sizer → 纯线性公式
            target_d, sizing_method, kelly_f, sizing_source = self._linear_only(
                score, macro_cap, position_limits,
            )

        # 风险偏好乘数
        target_d *= risk_mult_d

        # Phase 11: 操纵风险仓位折扣
        if manipulation_risk > 60:
            manip_discount = D("0.3")  # 高风险 → 仓位 3 折
        elif manipulation_risk > 30:
            manip_discount = D("0.7")  # 中风险 → 仓位 7 折
        elif manipulation_risk > 0:
            manip_discount = D("0.9")  # 低风险 → 轻微折扣
        else:
            manip_discount = D("1.0")
        target_d *= manip_discount

        # Phase 13: 超跌反弹仓位折扣
        oversold_discount = getattr(verdict, "oversold_position_discount", 1.0) or 1.0
        if oversold_discount < 1.0:
            target_d *= D(str(oversold_discount))

        # 双创折扣
        if is_gem:
            gem_discount = D("0.8")
            if position_limits:
                gem_discount = D(position_limits.get("gem_discount", 0.8))
            target_d *= gem_discount

        # 用户偏好单票上限 (二次确认)
        if position_limits:
            max_single = D(position_limits.get("single_stock_cap", 1.0))
            target_d = min(target_d, max_single)

        # 宏观仓位上限
        target_d = min(target_d, macro_cap_d)

        # 核心仓/交易仓区分
        if is_core:
            action = "HOLD" if action in ("REDUCE", "CLOSE") else action

        # Phase 4: Alpha 时序 — 叙事阶段决定仓位上限
        alpha_timing = ""
        if verdict.alpha_rationale:
            alpha_timing = verdict.alpha_rationale

        # Phase 7: 入场/出场时机注入
        # 注意: suggested_stop 直接来自入参（全量路径传入的 P0-3 止损建议），
        # timing_result 存在时由 timing_result 覆盖。
        entry_low = 0.0
        entry_high = 0.0
        exit_low = 0.0
        exit_high = 0.0
        time_stop_days = 60
        atr_stop = 0.0
        target_1 = 0.0
        target_2 = 0.0

        if timing_result is not None:
            if timing_result.best_entry:
                entry_low = timing_result.best_entry.entry_zone_low
                entry_high = timing_result.best_entry.entry_zone_high
            if timing_result.exit_signals:
                exit_low = timing_result.exit_signals[0].exit_zone_low
                exit_high = timing_result.exit_signals[0].exit_zone_high
            suggested_stop = timing_result.suggested_stop
            time_stop_days = timing_result.time_stop_days
            atr_stop = timing_result.atr_stop
            target_1 = timing_result.target_1
            target_2 = timing_result.target_2

        # P0-3: 单笔风险预算反推仓位 — 与乘数链结果取 min
        if action in ("OPEN", "ADD"):
            budget_capped = self._risk_budget_sizing(
                target_d,
                position_limits=position_limits,
                extra=extra,
                portfolio_value=portfolio_value,
                entry_price=entry_price,
                suggested_stop=suggested_stop,
            )
            if budget_capped is not None:
                target_d = budget_capped

        return TradeSignal(
            symbol=symbol,
            action=action,
            target_weight=round(float(target_d), 4),
            is_core=is_core,
            source_citations=verdict.source_citations,
            confidence=verdict.confidence,
            alpha_timing=alpha_timing,
            executive_risk=bool(getattr(verdict, "executive_risks", None)),
            sizing_method=sizing_method,
            kelly_f=kelly_f,
            kelly_params_source=sizing_source,
            name=name,
            extra=extra or {},
            entry_zone_low=entry_low,
            entry_zone_high=entry_high,
            exit_zone_low=exit_low,
            exit_zone_high=exit_high,
            suggested_stop=suggested_stop,
            time_stop_days=time_stop_days,
            atr_stop=atr_stop,
            target_1=target_1,
            target_2=target_2,
        )

    # ------------------------------------------------------------------
    # Phase 8: Signal + PortfolioTarget (LEAN Insight pattern)
    # ------------------------------------------------------------------

    def generate_signal_from_verdict(
        self,
        verdict: Verdict,
        time_horizon: str = "medium",
    ) -> Signal:
        """Convert a Verdict into a prediction Signal (LEAN Insight pattern).

        This is the new, methodologically clean path — separate the *what*
        (Signal) from the *how much* (PortfolioTarget).

        Args:
            verdict: 综合裁决结果 (Verdict from VerdictEngine).
            time_horizon: Prediction horizon ("short" / "medium" / "long").

        Returns:
            A Signal carrying direction, confidence, and audit metadata.
        """
        return signal_from_verdict(verdict, source_model="verdict_engine", time_horizon=time_horizon)

    @staticmethod
    def signal_to_target(
        signal: Signal,
        portfolio_value: float,
        current_price: float,
        max_weight: float = 1.0,
    ) -> PortfolioTarget:
        """Convert a Signal into an executable PortfolioTarget.

        This is the *how much* step — it takes the pure prediction from a
        Signal and, given the current portfolio value and market price,
        produces a concrete position target.

        Args:
            signal: The source Signal (prediction).
            portfolio_value: Total portfolio value.
            current_price: Current market price of the asset.
            max_weight: Maximum allowed allocation (0.0–1.0).

        Returns:
            A PortfolioTarget ready for execution / risk-control checks.
        """
        return target_from_signal(signal, portfolio_value, current_price, max_weight=max_weight)

    # ------------------------------------------------------------------
    # Phase 5: 凯利 + 线性
    # ------------------------------------------------------------------

    def _kelly_sizing(
        self,
        symbol: str,
        score: int,
        macro_cap: float,
        position_limits: Optional[dict],
        kelly_fraction: Optional[float],
    ) -> tuple[float, str, float, str]:
        """通过 KellyPositionSizer 计算仓位。"""
        result = self._kelly_sizer.calc(
            symbol=symbol,
            score=score,
            macro_cap=macro_cap,
            kelly_fraction=kelly_fraction,
            position_limits=position_limits,
        )
        logger.info(
            "Kelly sizing %s: method=%s target=%.1f%% f*=%.1f%% p=%.1f%% b=%.2f n=%d",
            symbol, result.method, result.target_weight * 100,
            result.kelly_f * 100, result.win_rate * 100,
            result.payoff_ratio, result.n_trades,
        )
        return (
            D(result.target_weight),
            result.method,
            result.kelly_f,
            result.source_citation,
        )

    @staticmethod
    def _linear_only(
        score: int,
        macro_cap: float,
        position_limits: Optional[dict],
    ) -> tuple[float, str, float, str]:
        """纯线性公式（无 Kelly sizer 时使用）。"""
        score_d = D(score)
        macro_cap_d = D(macro_cap)
        base_d = max(D("0"), (score_d - D("50")) / D("50") * macro_cap_d)
        if position_limits:
            max_single = D(position_limits.get("single_stock_cap", 1.0))
            base_d = min(base_d, max_single)
        return (
            base_d,
            "linear_fallback",
            0.0,
            f"linear:base=({score}-50)/50×{macro_cap}={float(base_d):.1%}",
        )

    # ------------------------------------------------------------------
    # P0-3: 单笔风险预算反推仓位
    # ------------------------------------------------------------------

    def _risk_budget_sizing(
        self,
        current: Decimal,
        position_limits: Optional[dict],
        extra: Optional[dict],
        portfolio_value: float,
        entry_price: float,
        suggested_stop: float,
    ) -> Optional[Decimal]:
        """单笔风险预算反推仓位上限，与乘数链结果取 min。

        公式: ``max_position = (equity × risk_budget_pct) / (entry − stop)``
        归一化为组合权重（除以 equity，equity 在归一化中约去）:
          ``max_weight = risk_budget_pct × entry / (entry − stop)``

        A 股 T+1 前置: 止损位须在建仓前已知。以下任一情况返回 None
        （回退现有乘数链逻辑，不报错）:
          - ``suggested_stop`` 缺失/≤0（timing 未给出止损）
          - 入场价缺失（entry_price 与 extra.price/close 均无）
          - stop >= entry（止损不低于入场 → 风险模型失效）
          - ``risk_budget_pct`` 未配置或 ≤0

        Args:
            current: 乘数链当前目标仓位（Decimal）
            position_limits: 用户偏好仓位约束（可含 risk_budget_pct / total_capital）
            extra: 行情 dict（入场价回退源）
            portfolio_value: 组合权益（risk-budget sizing 公式 equity）
            entry_price: 显式入场价
            suggested_stop: 建仓前已知的止损价（timing_result.suggested_stop）
        """
        pl = position_limits or {}
        risk_budget_pct = pl.get("risk_budget_pct", self.DEFAULT_RISK_BUDGET_PCT) or 0
        if risk_budget_pct <= 0 or suggested_stop <= 0:
            return None

        # 入场价: 显式参数 > extra 行情价
        entry = entry_price or 0
        if entry <= 0 and extra:
            entry = float(extra.get("price") or extra.get("close") or 0)
        if entry <= 0:
            return None

        per_share_risk = entry - suggested_stop
        if per_share_risk <= 0:
            return None

        # max_weight = risk_budget_pct × entry / (entry − stop)
        cap = (
            D(str(risk_budget_pct))
            * D(str(entry))
            / D(str(per_share_risk))
        )
        capped = min(current, cap)
        logger.info(
            "risk-budget sizing: entry=%.2f stop=%.2f budget=%.1f%% → cap=%.1f%% (current=%.1f%%)",
            entry, suggested_stop, risk_budget_pct * 100, float(cap) * 100,
            float(current) * 100,
        )
        return capped

    # ------------------------------------------------------------------
    # 评分 → 动作映射
    # ------------------------------------------------------------------

    def _score_to_action(self, score: int) -> str:
        if score >= 75:
            return "OPEN" if score >= 80 else "ADD"
        elif score >= 50:
            return "HOLD"
        elif score >= 35:
            return "REDUCE"
        else:
            return "CLOSE"

