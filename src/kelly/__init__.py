# -*- coding: utf-8 -*-
"""凯利公式仓位管理模块。

核心组件:
  - TradeTracker: 交易记录 CRUD + 按 symbol 汇总 p/b
  - KellyPositionSizer: 凯利仓位计算 (冷/热启动自适应)
"""

from .tracker import TradeTracker, TradeRecord, KellyParams
from .sizer import KellyPositionSizer

__all__ = [
    "TradeTracker",
    "TradeRecord",
    "KellyParams",
    "KellyPositionSizer",
]
