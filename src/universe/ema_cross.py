# -*- coding: utf-8 -*-
"""EmaCrossUniverseSelectionModel — 基于 EMA 动量的截面选股。

使用快慢 EMA 的偏离度对全市场股票排序，
选取偏离度最大的 Top N 支股票作为关注池。

这类似于 LEAN 的 ``FineFundamentalUniverseSelectionModel``
但使用技术面而非基本面指标。
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from .base import UniverseSelectionModel

logger = logging.getLogger(__name__)


class EmaCrossUniverseSelectionModel(UniverseSelectionModel):
    """EMA 偏离度选股模型。

    对每支股票计算 (fast_EMA - slow_EMA) / slow_EMA，
    值越大说明短期趋势相对长期趋势越强。
    取 Top N 作为选股池。

    Parameters
    ----------
    fast_period : int
        快 EMA 窗口，默认 100。
    slow_period : int
        慢 EMA 窗口，默认 300。
    universe_count : int
        选取的股票数量，默认 500。
    minimum_data : int
        每支股票所需的最小数据行数，少于该值则跳过。
    """

    def __init__(
        self,
        fast_period: int = 100,
        slow_period: int = 300,
        universe_count: int = 500,
        minimum_data: Optional[int] = None,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.universe_count = universe_count
        self.minimum_data = minimum_data or slow_period + 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_universe(self, data: pd.DataFrame) -> list[str]:
        """按 EMA 偏离度排序，选取 Top N 股票。

        Args:
            data: 列为股票代码、行为时间戳的收盘价 DataFrame。
                  示例::

                             000001.SZ  600519.SH   ...
                   2025-01-01   10.20     180.50
                   2025-01-02   10.35     182.00
                   ...

        Returns:
            按偏离度降序排列的股票代码列表，最多 ``universe_count`` 支。
        """
        if data.empty:
            return []

        scores: dict[str, float] = {}

        for symbol in data.columns:
            series = data[symbol].dropna()
            if len(series) < self.minimum_data:
                continue

            fast_ema = series.ewm(span=self.fast_period, adjust=False).mean()
            slow_ema = series.ewm(span=self.slow_period, adjust=False).mean()

            latest_fast = fast_ema.iloc[-1]
            latest_slow = slow_ema.iloc[-1]

            if latest_slow == 0:
                continue

            # 归一化偏离度: (快线 - 慢线) / 慢线
            deviation = (latest_fast - latest_slow) / latest_slow
            scores[symbol] = deviation

        if not scores:
            logger.warning("EmaCrossUniverse: no symbols passed minimum_data check")
            return []

        # 按偏离度降序排列
        sorted_symbols = sorted(scores, key=scores.__getitem__, reverse=True)

        result = sorted_symbols[: self.universe_count]

        logger.debug(
            "EmaCrossUniverse selected %d / %d candidates",
            len(result), len(scores),
        )

        return result

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(fast={self.fast_period}, slow={self.slow_period}, count={self.universe_count})"
        )
