# -*- coding: utf-8 -*-
"""L3 交易员 — 信号→仓位映射。Phase 4: Alpha 时序注入。Phase 5: 凯利公式仓位管理。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from .l2_judge import Verdict
from src.utils.decimal_utils import D, safe_divide

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """交易信号。"""
    symbol: str
    action: str            # OPEN / ADD / HOLD / REDUCE / CLOSE
    target_weight: float   # 目标仓位占比 (0.0 - 1.0)
    is_core: bool = False  # 是否核心仓操作
    limit: float = 0.0     # L4 施加的仓位上限
    source_citations: list = field(default_factory=list)  # Phase 1: 继承引用链
    confidence: float = 0.5  # Phase 1: 信号信心度
    alpha_timing: str = ""  # Phase 4: Alpha 时序提示 (叙事阶段 + 操作提示)
    executive_risk: bool = False  # V4: 高管风险标记
    # Phase 5: 凯利公式
    sizing_method: str = ""       # "kelly" / "linear_fallback" / "negative_expectation"
    kelly_f: float = 0.0          # 原始凯利 f*
    kelly_params_source: str = ""  # 凯利参数来源说明
    name: str = ""                # 股票名称 (for L4 黑名单/流动性检查)
    extra: dict = field(default_factory=dict)  # 原始行情数据 (for L4 黑名单检查)
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


class L3Trader:
    """L3 交易员。

    信号映射:
      - score ≥ 75 → 建仓/加仓
      - score 50-74 → 持有/观望
      - score 35-49 → 减仓
      - score < 35  → 清仓/回避

    Phase 5: 凯利公式仓位管理。
      - 热启动 (n≥5): target = kelly_fraction × f*, f* = (b×p - q)/b
      - 冷启动 (n<5): 回退线性公式 base = (score - 50) / 50 × macro_cap
      - 负期望 (f*≤0): target = 0，不建仓
    """

    def __init__(self, kelly_sizer=None):
        """初始化 L3 交易员。

        Args:
            kelly_sizer: KellyPositionSizer 实例 (可选)。None 时仅使用线性公式。
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
    ) -> TradeSignal:
        """生成交易信号。

        Args:
            verdict: L2 裁决结果
            macro_cap: 宏观仓位上限 (0.0-1.0)
            is_core: 是否核心仓 (阻止 REDUCE/CLOSE)
            is_gem: 是否双创 (创业板/科创板折扣)
            position_limits: 用户偏好仓位约束 {"single_stock_cap": ..., "kelly_fraction": ...}
            risk_multiplier: 风险偏好仓位乘数 (conservative=0.7, balanced=1.0, aggressive=1.2)
            timing_result: Phase 7 入场/出场时机结果 (仅短线/波段模式)
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
        entry_low = 0.0
        entry_high = 0.0
        exit_low = 0.0
        exit_high = 0.0
        suggested_stop = 0.0
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
