# -*- coding: utf-8 -*-
"""KellyPositionSizer — 凯利仓位计算。

冷/热启动自适应:
  - n_trades < 5: 回退线性公式 base = (score - 50) / 50 * macro_cap
  - n_trades >= 5: 使用 Half-Kelly (默认 kelly_fraction=0.5)
  - f* <= 0 (负期望): 返回 0，不建仓

风控联动:
  凯利输出后仍经过 风控单票上限/行业上限/回撤熔断等硬约束裁剪。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .tracker import KellyParams, TradeTracker
from src.utils.decimal_utils import D

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
            score: 裁决评分 (0-100)
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
        target = min(target, single_stock_cap)  # 风控单票上限
        target = min(target, macro_cap)
        """
        b_d = D(kp.payoff_ratio)
        p_d = D(kp.win_rate)
        q_d = D("1") - p_d
        fraction_d = D(fraction)

        # 凯利公式 — Decimal 精算
        raw_kelly_d = max(D("0"), (b_d * p_d - q_d) / b_d) if b_d > D("0") else D("0")

        # 分数凯利
        target_d = fraction_d * raw_kelly_d

        # 风控硬约束: 单票上限
        single_cap = D(position_limits.get("single_stock_cap", 1.0)) if position_limits else D("1.0")
        target_d = min(target_d, single_cap)

        # 宏观仓位上限
        target_d = min(target_d, D(macro_cap))

        raw_kelly_f = float(raw_kelly_d)
        method = "kelly"
        if raw_kelly_d <= D("0"):
            method = "negative_expectation"
            target_d = D("0")

        target_f = round(float(target_d), 4)
        return SizingResult(
            symbol=symbol,
            target_weight=target_f,
            method=method,
            kelly_f=round(raw_kelly_f, 4),
            kelly_fraction=round(fraction, 2),
            win_rate=kp.win_rate,
            payoff_ratio=kp.payoff_ratio,
            n_trades=kp.n_trades,
            source_citation=(
                f"kelly_f*={raw_kelly_f:.1%}(b={kp.payoff_ratio:.2f},p={kp.win_rate:.1%},n={kp.n_trades}),"
                f"fraction={fraction:.0%}→{target_f:.1%}"
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
        score_d = D(score)
        macro_cap_d = D(macro_cap)
        base_d = max(D("0"), (score_d - D("50")) / D("50") * macro_cap_d)

        # 风控约束
        if position_limits:
            base_d = min(base_d, D(position_limits.get("single_stock_cap", 1.0)))

        base_f = round(float(base_d), 4)
        return SizingResult(
            symbol=symbol,
            target_weight=base_f,
            method="linear_fallback",
            win_rate=kp.win_rate,
            payoff_ratio=kp.payoff_ratio,
            n_trades=kp.n_trades,
            source_citation=(
                f"linear_fallback(n={kp.n_trades}<{TradeTracker.MIN_TRADES_FOR_KELLY}):"
                f"base=({score}-50)/50×{macro_cap}={base_f:.1%}"
            ),
        )


# ------------------------------------------------------------------
# Phase 8: 波动率目标仓位法 (借鉴 RiskGuard sizing/volatility.py)
# ------------------------------------------------------------------

_MIN_VOL = 1e-6  # 防止除零/给出爆炸性权重


class VolatilityTargetSizer:
    """波动率目标仓位法。

    思路: 给每个头寸分配相同的"风险预算"而非相同的"资金"。
    目标权重 = 目标年化波动率 / 标的实现年化波动率。
    波动越大的标的仓位越小，波动越小的越大，从而让组合整体波动趋近目标。

    借鉴 RiskGuard ``VolatilityTargetSizer`` 设计。
    """

    name: str = "volatility_target"

    def __init__(
        self,
        target_vol: float = 0.15,
        lookback: int = 60,
    ):
        """初始化。

        Args:
            target_vol: 目标年化波动率 (默认 15%)
            lookback: 计算实现波动率的回溯天数 (默认 60)
        """
        if not (0.0 < target_vol <= 1.0):
            raise ValueError(f"target_vol must be in (0, 1], got {target_vol}")
        if lookback < 5:
            raise ValueError(f"lookback must be >= 5, got {lookback}")
        self.target_vol = target_vol
        self.lookback = lookback

    def target_weight(
        self,
        symbol: str,
        returns: list[float],
        macro_cap: float = 0.80,
        max_single: float = 0.20,
    ) -> SizingResult:
        """按 目标波动率 / 实现波动率 分配权重。

        Args:
            symbol: 标的代码
            returns: 日收益率序列 (至少 5 个数据点)
            macro_cap: 宏观仓位上限
            max_single: 单票上限

        Returns:
            SizingResult，volatility 相关参数通过 kelly_f 字段透传
        """
        if len(returns) < 5:
            return SizingResult(
                symbol=symbol,
                target_weight=0.0,
                method="vol_target_cold",
                source_citation=f"vol_target: need >=5 returns, got {len(returns)}",
            )

        # 日波动率
        import math
        n = min(len(returns), self.lookback)
        recent = returns[-n:]
        mean_ret = sum(recent) / n
        variance = sum((r - mean_ret) ** 2 for r in recent) / (n - 1) if n > 1 else 0.0
        daily_vol = math.sqrt(max(variance, 0.0))

        # 年化波动率 (sqrt(252) ≈ 15.875)
        annual_vol = daily_vol * math.sqrt(252)

        # 目标权重 = target_vol / max(annual_vol, _MIN_VOL)
        # _MIN_VOL 防御: 零波动率会导致爆炸性权重
        weight = self.target_vol / max(annual_vol, _MIN_VOL)

        # 夹到 [0, max_single] 再夹 macro_cap
        weight = min(weight, max_single)
        weight = min(weight, macro_cap)
        weight = max(0.0, round(weight, 4))

        return SizingResult(
            symbol=symbol,
            target_weight=weight,
            method="vol_target",
            kelly_f=annual_vol,  # 复用字段透传年化波动率
            kelly_fraction=self.target_vol,
            source_citation=(
                f"vol_target(annual_vol={annual_vol:.1%},"
                f"target={self.target_vol:.0%})→{weight:.1%}"
            ),
        )
