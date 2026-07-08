# -*- coding: utf-8 -*-
"""MomentumAlphaModel — 过去 N 日收益率动量 Alpha 模型。

过去 N 日收益率为正 → 买入信号 (UP), 趋势延续
过去 N 日收益率为负 → 卖出信号 (DOWN), 趋势反转/延续向下

是最基础的截面动量 / 时间序列动量模型。
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from src.routing.signal import Direction, Signal

from .base import AlphaModel

logger = logging.getLogger(__name__)


class MomentumAlphaModel(AlphaModel):
    """过去 N 日收益率动量 Alpha 模型。

    当价格在过去 ``lookback`` 个交易日上涨时发出 UP 信号，
    下跌时发出 DOWN 信号。

    Parameters
    ----------
    lookback : int
        收益率计算回看窗口（交易日数），默认 20 (= 约 1 个月)。
    symbol : str
        监控的股票代码。
    confidence_up : float
        上涨信号的置信度，默认 0.60。
    confidence_down : float
        下跌信号的置信度，默认 0.60。
    momentum_threshold : float
        最小收益率绝对值（百分比），低于此值不发信号，默认 0.0。
    """

    def __init__(
        self,
        lookback: int = 20,
        symbol: str = "",
        confidence_up: float = 0.60,
        confidence_down: float = 0.60,
        momentum_threshold: float = 0.0,
    ) -> None:
        self.lookback = lookback
        self.symbol = symbol
        self.confidence_up = confidence_up
        self.confidence_down = confidence_down
        self.momentum_threshold = momentum_threshold
        self.minimum_data = lookback + 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, market_data: pd.DataFrame) -> list[Signal]:
        """计算动量信号。

        Args:
            market_data: 至少包含 ``close`` 列的 DataFrame。

        Returns:
            当过去 N 日收益率超过阈值时返回一个 Signal，
            否则返回空列表。
        """
        if market_data.empty:
            return []

        close = market_data["close"].squeeze()
        if len(close) < self.minimum_data:
            return []

        # 过去 N 日收益率 (百分比)
        past_return = (close.iloc[-1] / close.iloc[-self.lookback - 1] - 1) * 100

        if abs(past_return) < self.momentum_threshold:
            return []

        if past_return > 0:
            direction = Direction.UP
            conf = self.confidence_up
        else:
            direction = Direction.DOWN
            conf = self.confidence_down

        logger.debug(
            "%s momentum %.2f%% over %d days → %s",
            self.symbol, past_return, self.lookback, direction.value,
        )

        return [
            Signal(
                symbol=self.symbol,
                direction=direction,
                confidence=conf,
                source_model=self.__class__.__name__,
                created_at=datetime.now(),
                magnitude=round(abs(past_return), 2),
                weight=None,
                time_horizon="medium",
                metadata={
                    "lookback": self.lookback,
                    "return_pct": round(past_return, 2),
                    "strategy": "momentum",
                },
            )
        ]

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(lookback={self.lookback}, symbol={self.symbol})"
        )
