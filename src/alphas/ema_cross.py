# -*- coding: utf-8 -*-
"""EmaCrossAlphaModel — 双均线交叉 Alpha 模型。

快线上穿慢线 → 买入信号 (UP)
快线下穿慢线 → 卖出信号 (DOWN)

均线交叉是最经典的动量追随策略之一。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from src.routing.signal import Direction, Signal

from .base import AlphaModel

logger = logging.getLogger(__name__)


class EmaCrossAlphaModel(AlphaModel):
    """指数移动平均线交叉 Alpha 模型。

    Parameters
    ----------
    fast_period : int
        快线窗口，默认 12 (类 MACD 标准快线)。
    slow_period : int
        慢线窗口，默认 26 (类 MACD 标准慢线)。
    symbol : str
        监控的股票代码。
    minimum_data : int
        计算所需的最少数据行数，不足时返回空列表。
    confidence : float
        信号置信度，默认 0.65。
    """

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        symbol: str = "",
        minimum_data: Optional[int] = None,
        confidence: float = 0.65,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.symbol = symbol
        self.minimum_data = minimum_data or slow_period + 1
        self.confidence = confidence

        # 缓存上一次的交叉关系，用于检测穿越事件
        self._prev_fast_above_slow: Optional[bool] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, market_data: pd.DataFrame) -> list[Signal]:
        """计算 EMA 交叉信号。

        Args:
            market_data: 至少包含 ``close`` 列的 DataFrame,
                         按时间升序排列。

        Returns:
            当快慢线产生新交叉时返回包含一个 Signal 的列表，
            否则返回空列表。
        """
        if market_data.empty:
            return []

        close = market_data["close"].squeeze()
        if len(close) < self.minimum_data:
            return []

        fast_ema = close.ewm(span=self.fast_period, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow_period, adjust=False).mean()

        fast_above_slow = fast_ema.iloc[-1] > slow_ema.iloc[-1]

        signals: list[Signal] = []

        if self._prev_fast_above_slow is not None:
            # 上穿
            if fast_above_slow and not self._prev_fast_above_slow:
                logger.debug(
                    "%s EMA cross UP (fast=%d > slow=%d)",
                    self.symbol, self.fast_period, self.slow_period,
                )
                signals.append(self._make_signal(Direction.UP))

            # 下穿
            elif not fast_above_slow and self._prev_fast_above_slow:
                logger.debug(
                    "%s EMA cross DOWN (fast=%d < slow=%d)",
                    self.symbol, self.fast_period, self.slow_period,
                )
                signals.append(self._make_signal(Direction.DOWN))

        self._prev_fast_above_slow = fast_above_slow
        return signals

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_signal(self, direction: Direction) -> Signal:
        """构建一个标准化的 Signal 实例。"""
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
                "fast_period": self.fast_period,
                "slow_period": self.slow_period,
                "strategy": "ema_cross",
            },
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(fast={self.fast_period}, slow={self.slow_period}, symbol={self.symbol})"
        )
