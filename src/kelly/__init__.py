# -*- coding: utf-8 -*-
"""凯利公式仓位管理模块。

核心组件:
  - TradeTracker: 交易记录 CRUD + 按 symbol 汇总 p/b
  - KellyPositionSizer: 凯利仓位计算 (冷/热启动自适应)
  - VolatilityTargetSizer: 波动率目标仓位法 (Phase 8)
  - EntryTrade / ExitTrade / PositionView: 交易三层视图 (Phase 8)
"""

from .tracker import (
    TradeTracker,
    TradeRecord,
    KellyParams,
    EntryTrade,
    ExitTrade,
    PositionView,
    build_entry_trades,
    build_exit_trades,
    build_positions,
    consistency_check,
)
from .sizer import KellyPositionSizer, VolatilityTargetSizer
from .base import Sizer

__all__ = [
    "TradeTracker",
    "TradeRecord",
    "KellyParams",
    "KellyPositionSizer",
    "VolatilityTargetSizer",
    "EntryTrade",
    "ExitTrade",
    "PositionView",
    "build_entry_trades",
    "build_exit_trades",
    "build_positions",
    "consistency_check",
    "Sizer",
]
