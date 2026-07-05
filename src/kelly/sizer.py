# -*- coding: utf-8 -*-
"""KellyPositionSizer — 凯利仓位计算。

冷/热启动自适应:
  - n_trades < 5: 回退线性公式 base = (score - 50) / 50 * macro_cap
  - n_trades >= 5: 使用 Half-Kelly (默认 kelly_fraction=0.5)
  - f* <= 0 (负期望): 返回 0，不建仓

L4 联动:
  凯利输出后仍经过 L4 单票上限/行业上限/回撤熔断等硬约束裁剪。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .tracker import KellyParams, TradeTracker

logger = logging.getLogger(__name__)


@dataclass
class SizingResult:
    """仓位计算结果。"""
    symbol: str
    target_weight: float          # 最终目标仓位 (0.0-1.0)
    method: str                   # "kelly" / "linear_fallback" / "negative_expectation"
    kelly_f: float = 0.0          # 原始凯利 f*
    kelly_fraction: float = 0.5   # 使用的凯利分数
    win_rate: float = 0.0         # p
    payoff_ratio: float = 0.0     # b
    n_trades: int = 0             # 样本数
    source_citation: str = ""     # Phase 1: 来源说明


class KellyPositionSizer:
    """凯利仓位计算器。

    用法:
        tracker = TradeTracker()
        sizer = KellyPositionSizer(tracker, default_kelly_fraction=0.5)

        # 热启动
        result = sizer.calc("600519", score=75, macro_cap=0.80)
        # → target_weight=0.18, method="kelly"

        # 冷启动
        result = sizer.calc("000001", score=70, macro_cap=0.80)
        # → target_weight=0.32, method="linear_fallback"
    """

    def __init__(
        self,
        tracker: TradeTracker,
        default_kelly_fraction: float = 0.5,
    ):
        self._tracker = tracker
        self._default_kelly_fraction = default_kelly_fraction

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def calc(
        self,
        symbol: str,
        score: int,
        macro_cap: float = 0.80,
        kelly_fraction: Optional[float] = None,
        position_limits: Optional[dict] = None,
    ) -> SizingResult:
        """计算凯利仓位。

        Args:
            symbol: 股票代码
            score: L2 评分 (0-100)
            macro_cap: 宏观仓位上限
            kelly_fraction: 凯利分数 (None=使用默认值, 0.3-1.0)
            position_limits: 用户偏好仓位约束 (含 single_stock_cap)

        Returns:
            SizingResult with target_weight and method
        """
        fraction = kelly_fraction if kelly_fraction is not None else self._default_kelly_fraction
        fraction = max(0.1, min(1.0, fraction))  # clamp [0.1, 1.0]

        kp = self._tracker.get_kelly_params(symbol)

        # 冷启动: 样本不足 → 回退线性公式
        if not kp.is_hot:
            return self._linear_fallback(symbol, score, macro_cap, kp, position_limits)

        # 热启动: 凯利公式
        return self._kelly_sizing(symbol, score, macro_cap, kp, fraction, position_limits)

    def calc_with_params(
        self,
        kp: KellyParams,
        score: int,
        macro_cap: float = 0.80,
        kelly_fraction: Optional[float] = None,
        position_limits: Optional[dict] = None,
    ) -> SizingResult:
        """直接使用 KellyParams 计算（跳过 tracker 查询）。

        用于回测场景：先算好 kp，再批量 sizing。
        """
        fraction = kelly_fraction if kelly_fraction is not None else self._default_kelly_fraction
        fraction = max(0.1, min(1.0, fraction))

        if not kp.is_hot:
            return self._linear_fallback(kp.symbol, score, macro_cap, kp, position_limits)

        return self._kelly_sizing(kp.symbol, score, macro_cap, kp, fraction, position_limits)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _kelly_sizing(
        self,
        symbol: str,
        score: int,
        macro_cap: float,
        kp: KellyParams,
        fraction: float,
        position_limits: Optional[dict],
    ) -> SizingResult:
        """凯利公式仓位计算。

        f* = (b × p - q) / b
        target = fraction × f* (默认 half-Kelly)
        target = min(target, L4 single_stock_cap)
        target = min(target, macro_cap)
        """
        b = kp.payoff_ratio
        p = kp.win_rate
        q = 1.0 - p

        # 凯利公式
        raw_kelly = max(0.0, (b * p - q) / b) if b > 0 else 0.0

        # 分数凯利
        target = fraction * raw_kelly

        # L4 硬约束: 单票上限
        single_cap = 1.0
        if position_limits:
            single_cap = position_limits.get("single_stock_cap", 1.0)
        target = min(target, single_cap)

        # 宏观仓位上限
        target = min(target, macro_cap)

        method = "kelly"
        if raw_kelly <= 0:
            method = "negative_expectation"
            target = 0.0

        return SizingResult(
            symbol=symbol,
            target_weight=round(target, 4),
            method=method,
            kelly_f=round(raw_kelly, 4),
            kelly_fraction=round(fraction, 2),
            win_rate=kp.win_rate,
            payoff_ratio=kp.payoff_ratio,
            n_trades=kp.n_trades,
            source_citation=(
                f"kelly_f*={raw_kelly:.1%}(b={b:.2f},p={p:.1%},n={kp.n_trades}),"
                f"fraction={fraction:.0%}→{target:.1%}"
            ),
        )

    def _linear_fallback(
        self,
        symbol: str,
        score: int,
        macro_cap: float,
        kp: KellyParams,
        position_limits: Optional[dict],
    ) -> SizingResult:
        """冷启动线性回退公式。

        base = (score - 50) / 50 * macro_cap
        """
        base = max(0, (score - 50) / 50 * macro_cap)

        # L4 约束
        if position_limits:
            base = min(base, position_limits.get("single_stock_cap", 1.0))

        return SizingResult(
            symbol=symbol,
            target_weight=round(base, 4),
            method="linear_fallback",
            win_rate=kp.win_rate,
            payoff_ratio=kp.payoff_ratio,
            n_trades=kp.n_trades,
            source_citation=(
                f"linear_fallback(n={kp.n_trades}<{TradeTracker.MIN_TRADES_FOR_KELLY}):"
                f"base=({score}-50)/50×{macro_cap}={base:.1%}"
            ),
        )
