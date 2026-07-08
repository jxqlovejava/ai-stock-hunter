# -*- coding: utf-8 -*-
"""UniverseSelectionModel 抽象基类 — 所有选股模型的契约。

表现层负责决定"分析哪些股票"，再交给 Alpha 模型出信号。

典型的用法::

    universe = EmaCrossUniverseSelectionModel()
    symbols = universe.select_universe(price_data)
    for sym in symbols:
        signals = alpha_model.update(sym_data[sym])
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class UniverseSelectionModel(ABC):
    """选股模型抽象基类。

    实现 ``select_universe()`` 方法，返回一个股票代码列表。
    子类可以维护内部状态（如上次选股时间、缓存结果等）。
    """

    @abstractmethod
    def select_universe(self, data: pd.DataFrame) -> list[str]:
        """从 ``data`` 中筛选出当前关注的股票池。

        Args:
            data: 包含多个股票行情数据的 DataFrame。
                  具体的列和索引结构由子类自行约定。

        Returns:
            选中的股票代码列表 (如 ``["000001.SZ", "600519.SH"]``)。
            空列表表示当前无符合条件的股票。
        """
        ...
