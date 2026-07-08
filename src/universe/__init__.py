# -*- coding: utf-8 -*-
"""Universe Selection — 股票池筛选 (LEAN UniverseSelectionModel 模式)。

决定"分析哪些股票"而不是"什么时候买卖"。
选股池的输出作为 Alpha 模型的输入种子。
"""

from .base import UniverseSelectionModel
from .ema_cross import EmaCrossUniverseSelectionModel
from .scheduled import ScheduledUniverseSelectionModel

__all__ = [
    "UniverseSelectionModel",
    "EmaCrossUniverseSelectionModel",
    "ScheduledUniverseSelectionModel",
]
