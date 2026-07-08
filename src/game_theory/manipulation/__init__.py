# -*- coding: utf-8 -*-
"""庄家操盘手法检测子包 (Phase 10: Manipulation Detection)。

提供 7 种经典庄家操纵模式的实时检测:
  - 诱多出货 (lure_bull_dump)
  - 诱空吸筹 (lure_bear_accumulate)
  - 对倒拉升 (wash_trade_pump)
  - 洗盘震仓 (shakeout)
  - 分时钓鱼线 (fishing_line)
  - 尾盘拉升 (closing_pump)
  - 尾盘砸盘 (closing_dump)
"""

from .detector import ManipulationDetector, ManipulationResult, ManipulationSignal
from .history import (
    ManipulationHistoryStore,
    ManipulationRecord,
    StockManipulationProfile,
    get_manipulation_risk_rating,
    log_manipulation_event,
)
from .sentiment_nexus import SentimentManipulationContext, SentimentManipulationNexus
from .sizing import (
    ManipulationSizingEngine,
    ManipulationSizingResult,
    ManipulationStopStrategy,
    quick_sizing,
)

__all__ = [
    "ManipulationDetector",
    "ManipulationHistoryStore",
    "ManipulationRecord",
    "ManipulationResult",
    "ManipulationSignal",
    "ManipulationSizingEngine",
    "ManipulationSizingResult",
    "ManipulationStopStrategy",
    "SentimentManipulationContext",
    "SentimentManipulationNexus",
    "StockManipulationProfile",
    "get_manipulation_risk_rating",
    "log_manipulation_event",
    "quick_sizing",
]
