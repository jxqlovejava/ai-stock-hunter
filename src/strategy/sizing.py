"""PositionSizer — unified position sizing from StrategySignal to PositionSize.

Integrates existing Kelly and volatility-target sizing from
``src/kelly/sizer.py``, plus a fixed-fractional fallback.

Usage::

    sizer = PositionSizer(kelly_sizer=KellyPositionSizer(tracker))
    size = sizer.calculate(signal, portfolio, atr=0.015, entry_price=42.5)
    # PositionSize(quantity=200, weight_pct=0.10, risk_pct=0.0036, ...)
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from src.kelly.sizer import KellyPositionSizer, VolatilityTargetSizer
from src.strategy.types import PositionSize, PortfolioSnapshot, StrategySignal
from src.utils.decimal_utils import D

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

MAX_POSITION_PCT: float = 0.20       # 单票仓位上限 20%
MAX_TOTAL_EXPOSURE: float = 1.0      # 组合总敞口上限 100%
MAX_RISK_PER_TRADE: float = 0.02     # 单笔最大风险 2%（组合百分比）
DEFAULT_WEIGHT_PCT: float = 0.10     # 固定分数法默认 10%
DEFAULT_KELLY_FRACTION: float = 0.25  # 四分之一凯利 (quarter-Kelly)
TARGET_VOL: float = 0.15             # 目标年化波动率 15%
MIN_VOL: float = 0.01                # 最小波动率（防除零）
ATR_WIN_MULTIPLE: float = 2.0        # 止盈 ATR 倍数
ATR_LOSS_MULTIPLE: float = 1.0       # 止损 ATR 倍数
BOARD_LOT: int = 100                 # A 股每手 100 股
SQRT_252: float = 15.8745            # sqrt(252) — 日→年化波动率


class PositionSizer:
    """统一仓位计算器，自动选择凯利 / 波动率目标 / 固定分数法。

    方法选择优先级:
      1. **kelly** — 当 ``kelly_sizer`` 可用且 ``signal.strength > 0``。
         win_rate = signal.strength, payoff_ratio = ATR_WIN_MULTIPLE / ATR_LOSS_MULTIPLE。
         凯利分数 = 0.25。若 f* ≤ 0 则返回 quantity=0。
      2. **vol_target** — 当 ``vol_sizer`` 可用且 atr/entry_price 合法。
         权重 = TARGET_VOL / max(realized_vol, MIN_VOL)。
      3. **fixed_fractional** — 回退方案，固定 10%。

    所有方法共享:
      - 单笔风险检查 (risk_pct ≤ MAX_RISK_PER_TRADE)
      - 单票上限 (MAX_POSITION_PCT)
      - 总敞口上限 (MAX_TOTAL_EXPOSURE)
      - A 股手数取整 (向下取至最近 100 股)

    Args:
        kelly_sizer: ``KellyPositionSizer`` 实例（来自 ``src/kelly/sizer.py``）。
        vol_sizer: ``VolatilityTargetSizer`` 实例。
    """

    def __init__(
        self,
        kelly_sizer: KellyPositionSizer | None = None,
        vol_sizer: VolatilityTargetSizer | None = None,
    ):
        self._kelly_sizer = kelly_sizer
        self._vol_sizer = vol_sizer

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    def calculate(
        self,
        signal: StrategySignal,
        portfolio: PortfolioSnapshot,
        atr: float = 0.01,
        entry_price: float = 0.0,
    ) -> PositionSize:
        """计算目标仓位。

        Args:
            signal: 策略信号（action / strength / direction 等）。
            portfolio: 组合快照（total_equity / positions）。
            atr: Average True Range，波动率估计值。
            entry_price: 预期入场价格。

        Returns:
            ``PositionSize`` 含手数取整后的 quantity。
        """
        # 入参守卫
        safe_price = max(entry_price, 0.01)
        total_equity = max(portfolio.total_equity, 1.0)

        # --- 方法选择 + 权重计算 ---
        weight_pct, method, raw_kelly = self._select_size(signal, atr, safe_price)

        # 负期望 / 无仓位 → 提前返回
        if weight_pct <= 0:
            return PositionSize(
                quantity=0, weight_pct=0.0, risk_pct=0.0,
                kelly_fraction=0.0, sizing_method=method,
            )

        # --- 风控：单笔风险检查 ---
        weight_pct, risk_pct = self._apply_risk_check(weight_pct, atr, safe_price)

        # --- 单票上限 ---
        weight_pct = min(weight_pct, MAX_POSITION_PCT)

        # --- 总敞口检查 ---
        current_exposure = self._current_exposure(portfolio)
        weight_pct = self._apply_exposure_cap(weight_pct, current_exposure)

        if weight_pct <= 0:
            return PositionSize(
                quantity=0, weight_pct=0.0, risk_pct=0.0,
                kelly_fraction=raw_kelly, sizing_method=method,
            )

        # --- 手数取整 ---
        quantity, actual_weight = self._round_to_board_lot(
            weight_pct, total_equity, safe_price,
        )

        if quantity <= 0:
            return PositionSize(
                quantity=0, weight_pct=0.0, risk_pct=0.0,
                kelly_fraction=raw_kelly, sizing_method=method,
            )

        # 实际风险占比（基于实际成交额重新计算）
        actual_risk = actual_weight * (atr / safe_price)

        return PositionSize(
            quantity=quantity,
            weight_pct=round(actual_weight, 4),
            risk_pct=round(min(actual_risk, 1.0), 6),
            kelly_fraction=round(raw_kelly, 4),
            sizing_method=method,
        )

    # ------------------------------------------------------------------
    #  Method selection
    # ------------------------------------------------------------------

    def _select_size(
        self,
        signal: StrategySignal,
        atr: float,
        entry_price: float,
    ) -> tuple[float, str, float]:
        """选择并执行三个方法之一，返回 (weight_pct, method, raw_kelly_f)。"""
        # 1) Kelly — 仅当有 sizer 且 signal 有有效强度
        if self._kelly_sizer is not None and signal.strength > 0:
            weight, raw_f = self._kelly_weight(signal.strength)
            if weight <= 0:
                return (0.0, "kelly", raw_f)
            return (weight, "kelly", raw_f)

        # 2) 波动率目标 — 仅当有 vol sizer 且价格/atr 合法
        if self._vol_sizer is not None and atr > 0 and entry_price > 0:
            weight = self._vol_weight(atr, entry_price)
            return (weight, "vol_target", 0.0)

        # 3) 固定分数法（回退）
        return (DEFAULT_WEIGHT_PCT, "fixed_fractional", 0.0)

    # ------------------------------------------------------------------
    #  Kelly sizing  (reuses formula from src/kelly/sizer.py)
    # ------------------------------------------------------------------

    @staticmethod
    def _kelly_weight(strength: float) -> tuple[float, float]:
        """凯利仓位上界。

        win_rate *p* = signal.strength (0.0–1.0)
        payoff_ratio *b* = ATR_WIN_MULTIPLE / ATR_LOSS_MULTIPLE

        f* = (b × p - q) / b,   q = 1 - p
        target = f* × DEFAULT_KELLY_FRACTION

        Returns:
            (target_weight, raw_f_star).
        """
        p_d = D(strength)
        b_d = D(ATR_WIN_MULTIPLE / ATR_LOSS_MULTIPLE)
        q_d = D("1") - p_d

        if b_d <= D("0"):
            return (0.0, 0.0)

        # 凯利公式（与 src/kelly/sizer.py 中 _kelly_sizing 相同数学）
        raw_f_d = max(D("0"), (b_d * p_d - q_d) / b_d)
        raw_f = float(raw_f_d)

        if raw_f <= 0:
            return (0.0, raw_f)

        target = raw_f * DEFAULT_KELLY_FRACTION
        return (target, raw_f)

    # ------------------------------------------------------------------
    #  Volatility target  (reuses formula from src/kelly/sizer.py)
    # ------------------------------------------------------------------

    @staticmethod
    def _vol_weight(atr: float, entry_price: float) -> float:
        """波动率目标权重。

        daily_vol = atr / entry_price
        annual_vol = daily_vol × sqrt(252)
        weight = TARGET_VOL / max(annual_vol, MIN_VOL)
        """
        if entry_price <= 0 or atr <= 0:
            return DEFAULT_WEIGHT_PCT

        daily_vol = atr / entry_price
        annual_vol = daily_vol * SQRT_252
        weight = TARGET_VOL / max(annual_vol, MIN_VOL)
        weight = min(weight, MAX_POSITION_PCT)
        return max(weight, 0.0)

    # ------------------------------------------------------------------
    #  Risk checks
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_risk_check(weight_pct: float, atr: float, entry_price: float) -> tuple[float, float]:
        """单笔风险检查。

        如果 risk_pct = weight × (atr / price) > MAX_RISK_PER_TRADE，
        等比缩小权重。
        """
        if entry_price <= 0 or atr <= 0:
            risk_pct = 0.0
            return (weight_pct, risk_pct)

        risk_pct = weight_pct * (atr / entry_price)
        if risk_pct > MAX_RISK_PER_TRADE:
            scale = MAX_RISK_PER_TRADE / risk_pct
            weight_pct *= scale
            risk_pct = weight_pct * (atr / entry_price)
            logger.info(
                "Risk check: scaled %.1f%% -> %.1f%% (risk=%.2f%%)",
                weight_pct / scale * 100, weight_pct * 100,
                risk_pct * 100,
            )
        return (weight_pct, min(risk_pct, 1.0))

    @staticmethod
    def _current_exposure(portfolio: PortfolioSnapshot) -> float:
        """当前组合总敞口（多空市值之和 / total_equity）。"""
        if portfolio.total_equity <= 0:
            return 0.0
        total_market_value = sum(
            pos.get("shares", 0) * pos.get("current_price", 0)
            for pos in portfolio.positions.values()
        )
        return total_market_value / portfolio.total_equity

    @staticmethod
    def _apply_exposure_cap(weight_pct: float, current_exposure: float) -> float:
        """组合总敞口上限裁剪。"""
        projected = current_exposure + weight_pct
        if projected <= MAX_TOTAL_EXPOSURE:
            return weight_pct
        if current_exposure >= MAX_TOTAL_EXPOSURE:
            return 0.0
        return MAX_TOTAL_EXPOSURE - current_exposure

    # ------------------------------------------------------------------
    #  Board-lot rounding
    # ------------------------------------------------------------------

    @staticmethod
    def _round_to_board_lot(
        weight_pct: float,
        total_equity: float,
        entry_price: float,
    ) -> tuple[int, float]:
        """按 A 股 100 股/手向下取整。

        Returns:
            (quantity, actual_weight_pct).
        """
        raw_shares = total_equity * weight_pct / entry_price
        raw_lots = int(raw_shares / BOARD_LOT)
        if raw_lots < 1:
            return (0, 0.0)

        quantity = raw_lots * BOARD_LOT
        actual_weight = quantity * entry_price / total_equity
        return (quantity, actual_weight)
