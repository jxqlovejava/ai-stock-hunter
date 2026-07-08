# -*- coding: utf-8 -*-
"""Indicators package — candlestick patterns, trend, oscillator, volatility & structure.

All indicators follow the LEAN-inspired hierarchy from ``base.py``:

    Indicator
    └── WindowIndicator  (rolling window of values)
        └── BarIndicator  (OHLC bar window)
            └── CandlestickPattern  (returns +1/0/-1)

Usage:

    from src.indicators.candlestick import Hammer, MorningStar
    from src.indicators.trend import HullMovingAverage, SuperTrend
    from src.indicators.oscillator import StochasticRSI, ConnorsRSI
    from src.indicators.volatility import ChoppinessIndex, ChaikinMoneyFlow
    from src.indicators.structure import HurstExponent, ZigZag

    hammer = Hammer()
    hammer.update((10, 12, 9, 11.5))  # (open, high, low, close)
    if hammer.is_ready:
        print(hammer.current_value)  # +1, 0, or -1
"""

from __future__ import annotations

# ── Base ────────────────────────────────────────────────────────────
from .base import (
    C,
    BarIndicator,
    CandleSettings,
    CandlestickPattern,
    H,
    Indicator,
    L,
    O,
    V,
    WindowIndicator,
    body_midpoint,
    candle_midpoint,
    candle_range,
    is_bearish,
    is_bullish,
    lower_shadow,
    real_body,
    upper_shadow,
)

# ── Candle Settings ────────────────────────────────────────────────
from .candle_settings import (
    DOJI_SETTINGS,
    FAR,
    FULL_BODY,
    HAMMER_SETTINGS,
    LONG_BODY,
    LONG_SHADOW,
    MARUBOZU_SETTINGS,
    NEAR,
    NONEXISTENT_SHADOW,
    SHORT_BODY,
    SHORT_SHADOW,
    TINY_BODY,
    TOLERANT,
)

# ── Candlestick Patterns ───────────────────────────────────────────
from .candlestick import (
    AdvanceBlock,
    BearishAbandonedBaby,
    BearishBeltHold,
    BearishCounterattack,
    BearishEngulfing,
    BearishHarami,
    BearishHaramiCross,
    BearishSeparatingLines,
    BearishTasukiGap,
    Breakaway,
    BullishAbandonedBaby,
    BullishBeltHold,
    BullishCounterattack,
    BullishEngulfing,
    BullishHarami,
    BullishHaramiCross,
    BullishSeparatingLines,
    BullishTasukiGap,
    ClosingMarubozu,
    ConcealingBabySwallow,
    DarkCloudCover,
    Doji,
    DragonflyDoji,
    EveningDojiStar,
    EveningStar,
    FallingThreeMethods,
    GapSideBySideWhite,
    GravestoneDoji,
    Hammer,
    HangingMan,
    HighWaveCandle,
    Hikkake,
    HikkakeModified,
    HomingPigeon,
    IdenticalThreeCrows,
    InNeck,
    InvertedHammer,
    Kicking,
    KickingByLength,
    LadderBottom,
    LongLeggedDoji,
    LongLineCandle,
    Marubozu,
    MatchingLow,
    MatHold,
    MorningDojiStar,
    MorningStar,
    OnNeck,
    Piercing,
    RickshawMan,
    RisingThreeMethods,
    ShootingStar,
    ShortLineCandle,
    SpinningTop,
    StalledPattern,
    StickSandwich,
    Takuri,
    ThreeBlackCrows,
    ThreeInsideDown,
    ThreeInsideUp,
    ThreeOutsideDown,
    ThreeOutsideUp,
    ThreeStarsInSouth,
    ThreeWhiteSoldiers,
    Thrusting,
    TriStar,
    TwoCrows,
    UniqueThreeRiver,
    UpDownGapThreeMethods,
    UpsideGapTwoCrows,
)

# ── Trend ──────────────────────────────────────────────────────────
from .trend import (
    DonchianChannel,
    DonchianChannelValue,
    HullMovingAverage,
    IchimokuKinkoHyo,
    IchimokuLines,
    KaufmanAdaptiveMovingAverage,
    ParabolicSAR,
    SuperTrend,
    SuperTrendValue,
)

# ── Oscillator ─────────────────────────────────────────────────────
from .oscillator import (
    AwesomeOscillator,
    ConnorsRSI,
    FisherTransform,
    StochasticRSI,
    UltimateOscillator,
    UltimateOscillatorOHLC,
)

# ── Volatility / Volume ────────────────────────────────────────────
from .volatility import (
    ChaikinMoneyFlow,
    ChoppinessIndex,
    ForceIndex,
    KeltnerChannelValue,
    KeltnerChannels,
)

# ── Structure ──────────────────────────────────────────────────────
from .structure import (
    HurstExponent,
    ZigZag,
    ZigZagPoint,
)


__all__ = [
    # Base
    "Indicator",
    "WindowIndicator",
    "BarIndicator",
    "CandlestickPattern",
    "CandleSettings",
    "O", "H", "L", "C", "V",
    "candle_range", "real_body", "upper_shadow", "lower_shadow",
    "is_bullish", "is_bearish", "body_midpoint", "candle_midpoint",
    # Settings
    "SHORT_BODY", "LONG_BODY", "TINY_BODY", "FULL_BODY",
    "SHORT_SHADOW", "LONG_SHADOW", "NONEXISTENT_SHADOW",
    "NEAR", "FAR", "TOLERANT",
    "DOJI_SETTINGS", "MARUBOZU_SETTINGS", "HAMMER_SETTINGS",
    # Candlestick patterns
    "Doji", "DragonflyDoji", "GravestoneDoji", "LongLeggedDoji", "RickshawMan",
    "Marubozu", "ClosingMarubozu", "SpinningTop", "HighWaveCandle",
    "LongLineCandle", "ShortLineCandle",
    "Hammer", "HangingMan", "ShootingStar", "InvertedHammer", "Takuri",
    "BullishEngulfing", "BearishEngulfing",
    "BullishHarami", "BearishHarami", "BullishHaramiCross", "BearishHaramiCross",
    "Piercing", "DarkCloudCover",
    "BullishBeltHold", "BearishBeltHold",
    "BullishCounterattack", "BearishCounterattack",
    "MatchingLow", "HomingPigeon", "InNeck", "OnNeck", "Thrusting",
    "BullishSeparatingLines", "BearishSeparatingLines",
    "MorningStar", "EveningStar", "MorningDojiStar", "EveningDojiStar",
    "BullishAbandonedBaby", "BearishAbandonedBaby",
    "ThreeWhiteSoldiers", "ThreeBlackCrows",
    "ThreeInsideUp", "ThreeInsideDown", "ThreeOutsideUp", "ThreeOutsideDown",
    "TriStar", "UniqueThreeRiver", "ThreeStarsInSouth",
    "AdvanceBlock", "StalledPattern",
    "BullishTasukiGap", "BearishTasukiGap",
    "GapSideBySideWhite", "UpDownGapThreeMethods",
    "ConcealingBabySwallow", "LadderBottom",
    "MatHold", "RisingThreeMethods", "FallingThreeMethods",
    "Breakaway", "StickSandwich",
    "IdenticalThreeCrows", "TwoCrows", "UpsideGapTwoCrows",
    "Kicking", "KickingByLength",
    "Hikkake", "HikkakeModified",
    # Trend
    "HullMovingAverage", "KaufmanAdaptiveMovingAverage",
    "IchimokuKinkoHyo", "IchimokuLines",
    "SuperTrend", "SuperTrendValue",
    "ParabolicSAR",
    "DonchianChannel", "DonchianChannelValue",
    # Oscillator
    "StochasticRSI", "UltimateOscillator", "UltimateOscillatorOHLC",
    "AwesomeOscillator", "FisherTransform", "ConnorsRSI",
    # Volatility
    "KeltnerChannels", "KeltnerChannelValue",
    "ChoppinessIndex", "ForceIndex", "ChaikinMoneyFlow",
    # Structure
    "HurstExponent", "ZigZag", "ZigZagPoint",
]
