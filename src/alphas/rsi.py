# -*- coding: utf-8 -*-
"""RsiAlphaModel — RSI 均值回复 Alpha 模型。

RSI 低于超卖阈值  → 买入信号 (UP), 预期价格均值回归向上
RSI 高于超买阈值  → 卖出信号 (DOWN), 预期价格均值回归向下

适用于震荡行情，在趋势行情中容易产生逆势信号。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from src.routing.signal import Direction, Signal

from .base import AlphaModel

logger = logging.getLogger(__name__)


class RsiAlphaModel(AlphaModel):
    """RSI 均值回复 Alpha 模型。

    Parameters
    ----------
    period : int
        RSI 计算窗口，默认 14 (威尔德标准)。
    oversold : float
        超卖阈值，默认 30。RSI 低于此值触发买入。
    overbought : float
        超买阈值，默认 70。RSI 高于此值触发卖出。
    symbol : str
        监控的股票代码。
    exit_threshold_gap : float
        避免阈值附近反复触发的最小差距，默认 5。
    confidence : float
        信号置信度，默认 0.55 (均值回复信号置信度通常低于趋势信号)。
    """

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        symbol: str = "",
        exit_threshold_gap: float = 5.0,
        confidence: float = 0.55,
    ) -> None:
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.symbol = symbol
        self.exit_threshold_gap = exit_threshold_gap
        self.confidence = confidence

        self.minimum_data = period + 1

        # 记录上次是否处于触发区域，避免重复发信号
        self._was_oversold: bool = False
        self._was_overbought: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, market_data: pd.DataFrame) -> list[Signal]:
        """计算 RSI 均值回复信号。

        当 RSI 进入超卖/超买区域时触发信号，
        并且在 RSI 离开触发区域之前不会重复发同方向信号，
        以避免阈值附近频繁触发。

        Args:
            market_data: 至少包含 ``close`` 列的 DataFrame。

        Returns:
            新触发时包含一个 Signal 的列表，否则为空列表。
        """
        if market_data.empty:
            return []

        close = market_data["close"].squeeze()
        if len(close) < self.minimum_data:
            return []

        rsi = self._compute_rsi(close)
        current_rsi = rsi.iloc[-1]

        signals: list[Signal] = []

        # 超卖 → 买入 (仅当之前不在超卖区时触发)
        if current_rsi < self.oversold:
            if not self._was_oversold:
                logger.debug(
                    "%s RSI oversold %.1f < %.0f → UP",
                    self.symbol, current_rsi, self.oversold,
                )
                signals.append(self._make_signal(Direction.UP, rsi_value=current_rsi))
            self._was_oversold = True
        else:
            # 退出超卖区，重置状态使下次进入时可重新触发
            self._was_oversold = False

        # 超买 → 卖出 (仅当之前不在超买区时触发)
        if current_rsi > self.overbought:
            if not self._was_overbought:
                logger.debug(
                    "%s RSI overbought %.1f > %.0f → DOWN",
                    self.symbol, current_rsi, self.overbought,
                )
                signals.append(self._make_signal(Direction.DOWN, rsi_value=current_rsi))
            self._was_overbought = True
        else:
            self._was_overbought = False

        return signals

    # ------------------------------------------------------------------
    # RSI 计算
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_rsi(close: pd.Series, period: Optional[int] = None) -> pd.Series:
        """计算相对强弱指标 (RSI)。

        使用 Wilder 平滑方法。
        """
        p = period or 14
        delta = close.diff()

        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)

        avg_gain = gain.ewm(alpha=1.0 / p, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / p, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, float("nan"))
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_signal(self, direction: Direction, rsi_value: float) -> Signal:
        return Signal(
            symbol=self.symbol,
            direction=direction,
            confidence=self.confidence,
            source_model=self.__class__.__name__,
            created_at=datetime.now(),
            magnitude=None,
            weight=None,
            time_horizon="short",
            metadata={
                "period": self.period,
                "oversold": self.oversold,
                "overbought": self.overbought,
                "rsi_value": round(rsi_value, 2),
                "strategy": "rsi_mean_reversion",
            },
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(period={self.period}, oversold={self.oversold}, "
            f"overbought={self.overbought}, symbol={self.symbol})"
        )
