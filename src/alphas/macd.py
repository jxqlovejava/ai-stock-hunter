# -*- coding: utf-8 -*-
"""MacdAlphaModel — MACD 指标 Alpha 模型。

MACD 线上穿信号线 → 买入信号 (UP)
MACD 线下穿信号线 → 卖出信号 (DOWN)

MACD = 快EMA - 慢EMA；信号线 = MACD 的 EMA。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from src.routing.signal import Direction, Signal

from .base import AlphaModel

logger = logging.getLogger(__name__)


class MacdAlphaModel(AlphaModel):
    """MACD Alpha 模型 — 趋势强度与动量转折。

    Parameters
    ----------
    fast : int
        MACD 快线周期，默认 12。
    slow : int
        MACD 慢线周期，默认 26。
    signal : int
        MACD 信号线周期，默认 9。
    symbol : str
        监控的股票代码。
    confidence : float
        信号置信度，默认 0.60。
    """

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        symbol: str = "",
        confidence: float = 0.60,
    ) -> None:
        self.fast = fast
        self.slow = slow
        self.signal_period = signal
        self.symbol = symbol
        self.confidence = confidence

        # 所需最小数据量 = 慢线 + 信号线才能产生有意义的 MACD 信号
        self.minimum_data = slow + signal

        self._prev_macd_above_signal: Optional[bool] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, market_data: pd.DataFrame) -> list[Signal]:
        """计算 MACD 交叉信号。

        Args:
            market_data: 至少包含 ``close`` 列的 DataFrame,
                         按时间升序排列。

        Returns:
            当 MACD 与信号线产生新交叉时返回一个 Signal，
            否则返回空列表。
        """
        if market_data.empty:
            return []

        close = market_data["close"].squeeze()
        if len(close) < self.minimum_data:
            return []

        # MACD 计算
        fast_ema = close.ewm(span=self.fast, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()

        macd_above_signal = macd_line.iloc[-1] > signal_line.iloc[-1]

        signals: list[Signal] = []

        if self._prev_macd_above_signal is not None:
            # MACD 上穿信号线
            if macd_above_signal and not self._prev_macd_above_signal:
                logger.debug("%s MACD cross UP", self.symbol)
                signals.append(self._make_signal(Direction.UP))

            # MACD 下穿信号线
            elif not macd_above_signal and self._prev_macd_above_signal:
                logger.debug("%s MACD cross DOWN", self.symbol)
                signals.append(self._make_signal(Direction.DOWN))

        self._prev_macd_above_signal = macd_above_signal
        return signals

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_signal(self, direction: Direction) -> Signal:
        return Signal(
            symbol=self.symbol,
            direction=direction,
            confidence=self.confidence,
            source_model=self.__class__.__name__,
            created_at=datetime.now(),
            magnitude=None,
            weight=None,
            time_horizon="medium",
            metadata={
                "fast": self.fast,
                "slow": self.slow,
                "signal_period": self.signal_period,
                "strategy": "macd",
            },
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(fast={self.fast}, slow={self.slow}, signal={self.signal_period}, symbol={self.symbol})"
        )
