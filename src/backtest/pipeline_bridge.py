# -*- coding: utf-8 -*-
"""管道桥接 — 将 routing 模块的风控/仓位引擎挂接到回测。

提供:
  - RiskControlBridge: 在回测事件循环中调用 RiskControlEngine
  - PositioningBridge: 将 Verdict → Signal → TargetWeight 映射

用法:
    cerebro = BaizeCerebro()
    cerebro.with_risk_control()  # 自动创建 RiskControlEngine
    cerebro.with_position_tracking()  # 自动创建 PositionStateManager
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BridgeConfig:
    """管道桥接配置。"""
    enable_risk_control: bool = True
    enable_position_tracking: bool = True
    max_single_stock_weight: float = 0.20
    max_sector_weight: float = 0.40
    max_drawdown_pct: float = 0.15
    breaker_enabled: bool = True
    stop_loss_enabled: bool = True
    stop_loss_pct: float = -0.08
    trailing_stop_enabled: bool = False
    trailing_stop_pct: float = 0.05
    take_profit_enabled: bool = False
    take_profit_pct: float = 0.30


# ------------------------------------------------------------------
# RiskControlBridge
# ------------------------------------------------------------------

class RiskControlBridge:
    """将 RiskControlEngine 挂接到回测事件循环。

    职责:
      - 每 bar 调用 observe_equity() 更新 HWM 和 drawdown
      - 每笔订单调用 check() 做硬约束裁决
      - 熔断期拒绝新开仓，放行平仓单
    """

    def __init__(
        self,
        engine=None,
        config: BridgeConfig | None = None,
    ):
        self._config = config or BridgeConfig()
        self._engine = engine
        self._breaker_tripped = False
        self._equity_history: list[float] = []
        self._hwm: float = 0.0
        self._drawdown: float = 0.0

        if self._engine is None:
            try:
                from src.routing.risk_control import RiskControlEngine
                self._engine = RiskControlEngine()
            except ImportError:
                logger.warning("RiskControlEngine not available")

    @property
    def breaker_tripped(self) -> bool:
        return self._breaker_tripped

    @property
    def drawdown(self) -> float:
        return self._drawdown

    def observe_equity(self, equity: float):
        """更新权益观测（每 bar）。"""
        # NaN 防御
        if not _safe_float(equity):
            return

        self._equity_history.append(equity)

        # 更新 HWM
        if equity > self._hwm:
            self._hwm = equity
            # HWM 新高时检查是否需要复位熔断
            if self._breaker_tripped:
                logger.info(f"HWM reset to {equity:.2f}, breaker auto-reset")
                self._breaker_tripped = False

        # 计算回撤
        if self._hwm > 0:
            self._drawdown = 1.0 - equity / self._hwm
        else:
            self._drawdown = 0.0

        # 自动熔断检查
        if self._config.breaker_enabled and self._drawdown >= self._config.max_drawdown_pct:
            if not self._breaker_tripped:
                logger.warning(
                    f"Breaker tripped: drawdown={self._drawdown:.2%} >= "
                    f"max={self._config.max_drawdown_pct:.2%}"
                )
                self._breaker_tripped = True

    def check_buy(self, symbol: str, weight: float, equity: float) -> tuple[bool, float, str]:
        """检查买入订单。

        Returns:
            (approved, adjusted_weight, reason)
        """
        # 熔断中 — 拒绝新开仓
        if self._breaker_tripped:
            return False, 0.0, "breaker_tripped"

        # 单票上限
        if weight > self._config.max_single_stock_weight:
            adjusted = self._config.max_single_stock_weight
            return True, adjusted, f"capped at {adjusted:.2%}"

        # 有 RiskControlEngine 则委托做详细检查
        if self._engine is not None:
            try:
                check = self._engine.check(
                    symbol=symbol,
                    direction=1,
                    weight=weight,
                    equity=equity,
                )
                if not check.passed:
                    return False, 0.0, "; ".join(check.violations)
            except Exception as e:
                logger.debug(f"RiskControlEngine.check error: {e}")

        return True, weight, "ok"

    def check_sell(self, symbol: str) -> tuple[bool, str]:
        """检查卖出订单 — 熔断期平仓单永不放行拒绝。"""
        return True, "ok"

    def reset_breaker(self):
        """人工复位熔断，HWM 归位到当前权益。"""
        if self._equity_history:
            self._hwm = self._equity_history[-1]
        self._breaker_tripped = False
        self._drawdown = 0.0
        logger.info(f"Breaker manually reset, HWM={self._hwm:.2f}")


# ------------------------------------------------------------------
# PositioningBridge
# ------------------------------------------------------------------

class PositioningBridge:
    """将 Verdict → TradeSignal → 目标权重 映射到回测策略。

    在 strategy.next() 中调用:
      bridge = PositioningBridge(positioning_engine, data_map)
      weights = bridge.generate_weights(date, symbols)

    Returns:
      dict[symbol, target_weight]
    """

    def __init__(self, positioning_engine=None):
        self._engine = positioning_engine
        self._last_weights: dict[str, float] = {}

    def generate_weights(
        self,
        date,
        symbols: list[str],
        scores: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """生成目标权重。

        Args:
            date: 当前日期
            symbols: 候选标的
            scores: {symbol: score} 可选评分

        Returns:
            {symbol: target_weight (0.0-1.0)}
        """
        if self._engine is not None:
            try:
                # 调用 PositioningEngine.generate_signals()
                signals = self._engine.generate_signals(
                    symbols=symbols,
                    scores=scores or {},
                )
                weights = {s.symbol: s.target_weight for s in signals}
                self._last_weights = weights
                return weights
            except Exception as e:
                logger.debug(f"PositioningEngine error: {e}")

        # 回退: 等权
        if scores:
            total = sum(scores.values())
            if total > 0:
                weights = {s: v / total for s, v in scores.items()}
            else:
                n = len(symbols)
                weights = {s: 1.0 / n for s in symbols} if n > 0 else {}
        else:
            n = len(symbols)
            weights = {s: 1.0 / n for s in symbols} if n > 0 else {}

        self._last_weights = weights
        return weights


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def _safe_float(value) -> bool:
    """防御 NaN/Inf。"""
    import math
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
