# -*- coding: utf-8 -*-
"""庄家操盘手法检测子包 (Phase 10: Manipulation Detection + Phase 11: Washout Detection)。

提供 7 种经典庄家操纵模式的实时检测:
  - 诱多出货 (lure_bull_dump)
  - 诱空吸筹 (lure_bear_accumulate)
  - 对倒拉升 (wash_trade_pump)
  - 洗盘震仓 (shakeout)
  - 分时钓鱼线 (fishing_line)
  - 尾盘拉升 (closing_pump)
  - 尾盘砸盘 (closing_dump)

提供 7 种洗盘阶段特征检测:
  - 高开低走洗盘 (washout_high_open_low)
  - 低开高走洗盘 (washout_low_open_high)
  - 分时单边下跌 (washout_one_sided_decline)
  - 持续压低 (washout_continuous_suppression)
  - 连续阴线洗盘 (washout_consecutive_yin)
  - 击穿支撑位 (washout_support_breakdown)
  - 小涨大跌K线形态 (washout_small_rise_big_drop)
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
from .washout_detector import WashoutDetector, WashoutResult

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
    "WashoutDetector",
    "WashoutResult",
    "get_manipulation_risk_rating",
    "log_manipulation_event",
    "quick_sizing",
]
