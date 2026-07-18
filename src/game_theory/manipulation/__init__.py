# -*- coding: utf-8 -*-
"""庄家操盘手法检测子包 (Phase 10/11 + 多波洗盘生命周期)。

提供 7 种经典庄家操纵模式的实时检测:
  - 诱多出货 (lure_bull_dump)
  - 诱空吸筹 (lure_bear_accumulate)
  - 对倒拉升 (wash_trade_pump)
  - 洗盘震仓 (shakeout)
  - 分时钓鱼线 (fishing_line)
  - 尾盘拉升 (closing_pump)
  - 尾盘砸盘 (closing_dump)

提供洗盘阶段特征检测:
  - 高开低走 / 低开高走 / 分时单边下跌 / 持续压低
  - 连续阴线 / 击穿支撑 / 小涨大跌

多波生命周期（与上列形态互补，不重复）:
  - wash_then_markup: 连杀→后半段割肉→再洗→砸不动才拉
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
from .wash_cycle import WashCycleAnalyzer, WashCyclePhase, WashCycleResult
from .wash_backtest import (
    WashBacktestReport,
    WashCycleBacktester,
    WashEvent,
    run_wash_backtest,
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
    "WashBacktestReport",
    "WashCycleAnalyzer",
    "WashCycleBacktester",
    "WashCyclePhase",
    "WashCycleResult",
    "WashEvent",
    "WashoutDetector",
    "WashoutResult",
    "get_manipulation_risk_rating",
    "log_manipulation_event",
    "quick_sizing",
    "run_wash_backtest",
]
