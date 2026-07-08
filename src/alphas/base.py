# -*- coding: utf-8 -*-
"""AlphaModel 抽象基类 — 所有 Alpha 模型的契约。

LEAN 框架的 Insight-producing 模式：
- AlphaModel 负责从市场数据中提取预测信号 (Signal)。
- Signal 是纯预测，不包含仓位信息 — 仓位调度层负责转换。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from src.routing.signal import Signal


class AlphaModel(ABC):
    """Alpha 模型抽象基类。

    所有具体的 Alpha 策略 (均线交叉、MACD、RSI、动量等)
    都继承此类并实现 ``update()`` 方法。

    用法::

        model = EmaCrossAlphaModel(fast_period=12, slow_period=26, symbol="000001.SZ")
        signals = model.update(market_data_df)
        for sig in signals:
            print(sig.direction, sig.confidence)
    """

    @abstractmethod
    def update(self, market_data: pd.DataFrame) -> list[Signal]:
        """处理新的市场数据并返回一组信号。

        Args:
            market_data: 包含历史价格/成交量的 DataFrame,
                         至少需要 ``close`` 列，索引为 ``datetime``。

        Returns:
            当前时间片产生的 Signal 列表。可以为空列表。
        """
        ...
