# -*- coding: utf-8 -*-
"""63+ Japanese candlestick patterns — LEAN-inspired implementation.

Every pattern extends ``CandlestickPattern`` and returns:
    +1  bullish signal
     0  no signal
    -1  bearish signal

Patterns are organised by candle count (1, 2, 3, 4+).  All use the shared
helpers from ``base`` for body/shadow measurements and proximity checks.
"""

from __future__ import annotations

from typing import Optional

from .base import (
    C,
    CandlestickPattern,
    CandleSettings,
    H,
    L,
    O,
    V,
    body_midpoint,
    candle_midpoint,
    candle_range,
    is_bearish,
    is_bullish,
    lower_shadow,
    real_body,
    upper_shadow,
)

# ===================================================================
# Candle-level helpers (private to this module)
# ===================================================================


def _body_pct(bar: tuple) -> float:
    rng = candle_range(bar)
    return 0.0 if rng == 0.0 else real_body(bar) / rng


def _is_doji(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    if s is None:
        s = CandleSettings()
    return _body_pct(bar) < s.body_short


def _has_long_body(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    if s is None:
        s = CandleSettings()
    return _body_pct(bar) > s.body_long


def _has_short_body(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    if s is None:
        s = CandleSettings()
    return _body_pct(bar) < s.body_short


def _upper_pct(bar: tuple) -> float:
    rng = candle_range(bar)
    return 0.0 if rng == 0.0 else upper_shadow(bar) / rng


def _lower_pct(bar: tuple) -> float:
    rng = candle_range(bar)
    return 0.0 if rng == 0.0 else lower_shadow(bar) / rng


def _has_long_upper(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    if s is None:
        s = CandleSettings()
    return _upper_pct(bar) > s.shadow_long


def _has_long_lower(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    if s is None:
        s = CandleSettings()
    return _lower_pct(bar) > s.shadow_long


def _has_short_upper(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    if s is None:
        s = CandleSettings()
    return _upper_pct(bar) < s.shadow_short


def _has_short_lower(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    if s is None:
        s = CandleSettings()
    return _lower_pct(bar) < s.shadow_short


def _gaps_down(curr: tuple, prev: tuple) -> bool:
    return curr[H] < prev[L]


def _gaps_up(curr: tuple, prev: tuple) -> bool:
    return curr[L] > prev[H]


def _near(a: float, b: float, s: Optional[CandleSettings] = None) -> bool:
    if s is None:
        s = CandleSettings()
    ref = max(abs(a), 1e-12)
    return abs(a - b) / ref < s.near


def _eq(a: float, b: float, s: Optional[CandleSettings] = None) -> bool:
    if s is None:
        s = CandleSettings()
    ref = max(abs(a), 1e-12)
    return abs(a - b) / ref < s.equality


def _inside(curr: tuple, outer: tuple) -> bool:
    """True if curr's body is entirely inside outer's body."""
    oc, oo = max(outer[O], outer[C]), min(outer[O], outer[C])
    cc, co = max(curr[O], curr[C]), min(curr[O], curr[C])
    return co >= oo and cc <= oc


def _engulfs(curr: tuple, prev: tuple) -> bool:
    """True if curr's body completely engulfs prev's body."""
    return _inside(prev, curr)


def _avg_close(window: list[tuple], n: int) -> float:
    """Average close of the last n bars."""
    relevant = window[-n:] if n <= len(window) else window
    return sum(b[C] for b in relevant) / max(len(relevant), 1)


def _uptrend(window: list[tuple], lookback: int = 3) -> bool:
    """Check whether the N bars *before the trigger* show rising closes.

    The trigger candle (window[-1]) is excluded from the trend assessment.
    Requires at least ``lookback`` prior bars (minimum lookback = 2).
    """
    if len(window) <= lookback or lookback < 2:
        return False
    # Bars before the trigger candle
    recent = window[-(lookback + 1) : -1]
    return all(recent[i][C] >= recent[i - 1][C] for i in range(1, len(recent)))


def _downtrend(window: list[tuple], lookback: int = 3) -> bool:
    """Check whether the N bars *before the trigger* show falling closes.

    The trigger candle (window[-1]) is excluded from the trend assessment.
    Requires at least ``lookback`` prior bars (minimum lookback = 2).
    """
    if len(window) <= lookback or lookback < 2:
        return False
    recent = window[-(lookback + 1) : -1]
    return all(recent[i][C] <= recent[i - 1][C] for i in range(1, len(recent)))


def _is_gravestone_doji(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    return (
        _has_short_upper(bar, s) is False
        and _has_long_upper(bar, s)
        and _has_short_lower(bar, s)
        and _is_doji(bar, s)
    )


def _is_dragonfly_doji(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    return (
        _has_short_lower(bar, s) is False
        and _has_long_lower(bar, s)
        and _has_short_upper(bar, s)
        and _is_doji(bar, s)
    )


def _is_marubozu(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    return (
        _has_long_body(bar, s)
        and _has_short_upper(bar, s)
        and _has_short_lower(bar, s)
    )


def _is_hammer_like(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    """Candle shape: small body near top, long lower shadow."""
    if s is None:
        s = CandleSettings()
    return (
        _has_short_body(bar, s)
        and _has_long_lower(bar, s)
        and _has_short_upper(bar, s)
    )


def _is_shooting_star_like(bar: tuple, s: Optional[CandleSettings] = None) -> bool:
    """Candle shape: small body near bottom, long upper shadow."""
    if s is None:
        s = CandleSettings()
    return (
        _has_short_body(bar, s)
        and _has_long_upper(bar, s)
        and _has_short_lower(bar, s)
    )


# ===================================================================
# 1. SINGLE-CANDLE PATTERNS  (period=1)
# ===================================================================


class Doji(CandlestickPattern):
    """Open and close are nearly equal."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("Doji", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        return 0  # Doji alone is neutral; see specific variants


class DragonflyDoji(CandlestickPattern):
    """Doji with a long lower shadow and no upper shadow.

    Bullish reversal signal when occurring in downtrend.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("DragonflyDoji", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        if not _is_doji(bar, self._s):
            return 0
        if not _has_long_lower(bar, self._s):
            return 0
        if not _has_short_upper(bar, self._s):
            return 0
        if _downtrend(window, 2):
            return 1
        return -1 if _uptrend(window, 2) else 0


class GravestoneDoji(CandlestickPattern):
    """Doji with a long upper shadow and no lower shadow.

    Bearish reversal signal when occurring in uptrend.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("GravestoneDoji", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        if not _is_doji(bar, self._s):
            return 0
        if not _has_long_upper(bar, self._s):
            return 0
        if not _has_short_lower(bar, self._s):
            return 0
        if _uptrend(window, 2):
            return -1
        return 1 if _downtrend(window, 2) else 0


class LongLeggedDoji(CandlestickPattern):
    """Doji with long upper and lower shadows, both extending beyond range."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("LongLeggedDoji", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        if not _is_doji(bar, self._s):
            return 0
        if not _has_long_upper(bar, self._s):
            return 0
        if not _has_long_lower(bar, self._s):
            return 0
        # Long-legged doji signals indecision — neutral by itself but context matters
        return 1 if _downtrend(window, 1) else (-1 if _uptrend(window, 1) else 0)


class RickshawMan(CandlestickPattern):
    """Long-legged doji with very small body — extreme indecision."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("RickshawMan", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        # RickshawMan is a long-legged doji with a particularly tiny body
        if not _has_long_upper(bar, self._s) or not _has_long_lower(bar, self._s):
            return 0
        if _body_pct(bar) > self._s.body_short * 0.5:
            return 0
        return 1 if _downtrend(window, 1) else (-1 if _uptrend(window, 1) else 0)


class Marubozu(CandlestickPattern):
    """Long body with no shadows — strong directional conviction.

    Bullish Marubozu = white body, Bearish Marubozu = black body.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("Marubozu", period=1)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        if not _has_long_body(bar, self._s):
            return 0
        if not _has_short_upper(bar, self._s):
            return 0
        if not _has_short_lower(bar, self._s):
            return 0
        return 1 if is_bullish(bar) else -1


class ClosingMarubozu(CandlestickPattern):
    """Marubozu with one shadow (at the open side).

    Bullish: long white body, no lower shadow, close at high.
    Bearish: long black body, no upper shadow, close at low.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ClosingMarubozu", period=1)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        if not _has_long_body(bar, self._s):
            return 0
        if is_bullish(bar):
            return 1 if _has_short_lower(bar, self._s) else 0
        else:
            return -1 if _has_short_upper(bar, self._s) else 0


class SpinningTop(CandlestickPattern):
    """Small body with moderate shadows — indecision.

    Neutral by itself; signals potential reversal in context.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("SpinningTop", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        if not _has_short_body(bar, self._s):
            return 0
        # Must have both shadows (neither negligible)
        if _has_short_upper(bar, self._s) or _has_short_lower(bar, self._s):
            return 0
        # Must NOT be a doji (body some but small)
        if _is_doji(bar, self._s):
            return 0
        # In downtrend context it can signal reversal
        if _downtrend(window, 1):
            return 1
        if _uptrend(window, 1):
            return -1
        return 0


class HighWaveCandle(CandlestickPattern):
    """Very small body with very long shadows — extreme indecision."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("HighWaveCandle", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        if _body_pct(bar) > 0.15:
            return 0
        if not _has_long_upper(bar, self._s) and not _has_long_lower(bar, self._s):
            return 0
        # At least one shadow must be truly long
        return 1 if _downtrend(window, 1) else (-1 if _uptrend(window, 1) else 0)


class LongLineCandle(CandlestickPattern):
    """A candle with a long body (directional)."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("LongLineCandle", period=1)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        if not _has_long_body(bar, self._s):
            return 0
        return 1 if is_bullish(bar) else -1


class ShortLineCandle(CandlestickPattern):
    """A candle with a short body — generally neutral."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ShortLineCandle", period=1)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        return 1 if _has_short_body(bar, self._s) and is_bullish(bar) else 0


class Hammer(CandlestickPattern):
    """Small body near top, long lower shadow — bullish reversal in downtrend."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("Hammer", period=4)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if not _downtrend(window, 3):
            return 0
        bar = window[-1]
        return 1 if _is_hammer_like(bar, self._s) else 0


class HangingMan(CandlestickPattern):
    """Same shape as Hammer but in uptrend — bearish reversal."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("HangingMan", period=4)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if not _uptrend(window, 3):
            return 0
        bar = window[-1]
        return -1 if _is_hammer_like(bar, self._s) else 0


class ShootingStar(CandlestickPattern):
    """Small body near bottom, long upper shadow — bearish reversal in uptrend."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ShootingStar", period=4)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if not _uptrend(window, 3):
            return 0
        bar = window[-1]
        return -1 if _is_shooting_star_like(bar, self._s) else 0


class InvertedHammer(CandlestickPattern):
    """Same shape as Shooting Star but in downtrend — bullish reversal."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("InvertedHammer", period=4)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if not _downtrend(window, 3):
            return 0
        bar = window[-1]
        return 1 if _is_shooting_star_like(bar, self._s) else 0


class Takuri(CandlestickPattern):
    """Hammer-like but with an extremely long lower shadow — very bullish in downtrend."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("Takuri", period=4)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if not _downtrend(window, 3):
            return 0
        bar = window[-1]
        if not _has_short_body(bar, self._s):
            return 0
        if not _has_short_upper(bar, self._s):
            return 0
        # Takuri requires a *very* long lower shadow (>50% of range)
        if _lower_pct(bar) < 0.50:
            return 0
        return 1


# ===================================================================
# 2. TWO-CANDLE PATTERNS  (period=2)
# ===================================================================


class BullishEngulfing(CandlestickPattern):
    """Bearish candle followed by a bullish candle that engulfs it.

    Bullish reversal signal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BullishEngulfing", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p) or not is_bullish(c):
            return 0
        return 1 if _engulfs(c, p) else 0


class BearishEngulfing(CandlestickPattern):
    """Bullish candle followed by a bearish candle that engulfs it.

    Bearish reversal signal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BearishEngulfing", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bullish(p) or not is_bearish(c):
            return 0
        return -1 if _engulfs(c, p) else 0


class BullishHarami(CandlestickPattern):
    """Long bearish candle followed by a small bullish candle inside its body.

    Bullish reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BullishHarami", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p) or not is_bullish(c):
            return 0
        if not _has_long_body(p, self._s):
            return 0
        return 1 if _inside(c, p) else 0


class BearishHarami(CandlestickPattern):
    """Long bullish candle followed by a small bearish candle inside its body.

    Bearish reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BearishHarami", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bullish(p) or not is_bearish(c):
            return 0
        if not _has_long_body(p, self._s):
            return 0
        return -1 if _inside(c, p) else 0


class BullishHaramiCross(CandlestickPattern):
    """Long bearish candle followed by a doji inside its body.

    Stronger reversal than Harami.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BullishHaramiCross", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p):
            return 0
        if not _has_long_body(p, self._s):
            return 0
        if not _is_doji(c, self._s):
            return 0
        return 1 if _inside(c, p) else 0


class BearishHaramiCross(CandlestickPattern):
    """Long bullish candle followed by a doji inside its body."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BearishHaramiCross", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bullish(p):
            return 0
        if not _has_long_body(p, self._s):
            return 0
        if not _is_doji(c, self._s):
            return 0
        return -1 if _inside(c, p) else 0


class Piercing(CandlestickPattern):
    """Bearish candle followed by bullish that opens below previous low
    and closes above previous midpoint — bullish reversal.

    The bullish candle "pierces" into the bearish body.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("Piercing", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p) or not is_bullish(c):
            return 0
        # Bullish opens below previous low
        if c[O] >= p[L]:
            return 0
        # Bullish closes above previous midpoint
        pmid = body_midpoint(p)
        if c[C] <= pmid:
            return 0
        # Must not fully engulf the previous body (that's Engulfing)
        p_body_top = max(p[O], p[C])
        p_body_bot = min(p[O], p[C])
        if c[C] >= p_body_top and c[O] <= p_body_bot:
            return 0
        return 1


class DarkCloudCover(CandlestickPattern):
    """Bullish candle followed by bearish that opens above previous high
    and closes below previous midpoint — bearish reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("DarkCloudCover", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bullish(p) or not is_bearish(c):
            return 0
        # Bearish opens above previous high
        if c[O] <= p[H]:
            return 0
        # Bearish closes below previous midpoint
        pmid = body_midpoint(p)
        if c[C] >= pmid:
            return 0
        if c[C] <= p[O]:
            return 0
        return -1


class BullishBeltHold(CandlestickPattern):
    """Bullish candle that opens at the low of the day and closes near the high,
    with no lower shadow. Also known as White Opening Shaven Head.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BullishBeltHold", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        if not is_bullish(bar):
            return 0
        # Open = low (no lower shadow)
        if not _near(bar[O], bar[L], self._s):
            return 0
        if not _has_long_body(bar, self._s):
            return 0
        # Context: downtrend makes it more bullish
        return 1 if _downtrend(window, 1) else 1  # always signal but stronger in downtrend


class BearishBeltHold(CandlestickPattern):
    """Bearish candle that opens at the high of the day and closes near the low,
    with no upper shadow. Also known as Black Opening Shaven Head.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BearishBeltHold", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        bar = window[-1]
        if not is_bearish(bar):
            return 0
        if not _near(bar[O], bar[H], self._s):
            return 0
        if not _has_long_body(bar, self._s):
            return 0
        return -1


class BullishCounterattack(CandlestickPattern):
    """Bearish candle followed by a bullish that opens lower but closes exactly
    at the previous close — potential reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BullishCounterattack", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p) or not is_bullish(c):
            return 0
        if not _near(c[C], p[C], self._s):
            return 0
        if not _has_long_body(p, self._s) or not _has_long_body(c, self._s):
            return 0
        return 1


class BearishCounterattack(CandlestickPattern):
    """Bullish candle followed by a bearish that opens higher but closes exactly
    at the previous close — potential reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BearishCounterattack", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bullish(p) or not is_bearish(c):
            return 0
        if not _near(c[C], p[C], self._s):
            return 0
        if not _has_long_body(p, self._s) or not _has_long_body(c, self._s):
            return 0
        return -1


class MatchingLow(CandlestickPattern):
    """Two consecutive bearish candles with the same low price — bullish reversal."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("MatchingLow", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p) or not is_bearish(c):
            return 0
        if not _near(c[L], p[L], self._s):
            return 0
        return 1


class HomingPigeon(CandlestickPattern):
    """Two bearish candles where the second closes inside the first's body.
    Bullish reversal (weaker than Harami).
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("HomingPigeon", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p) or not is_bearish(c):
            return 0
        if not _has_long_body(p, self._s):
            return 0
        if not _inside(c, p):
            return 0
        # Both should close lower but second less so
        return 1


class InNeck(CandlestickPattern):
    """Bearish candle followed by a bullish that closes near the previous low,
    but does not penetrate. Bearish continuation.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("InNeck", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p) or not is_bullish(c):
            return 0
        if not _near(c[C], p[L], self._s):
            return 0
        return -1


class OnNeck(CandlestickPattern):
    """Bearish candle followed by a bullish that touches the previous low.
    Bearish continuation (weaker than InNeck).
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("OnNeck", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p) or not is_bullish(c):
            return 0
        if not _near(c[C], p[L], self._s):
            return 0
        # OnNeck: second candle closes right at the low
        if not _near(c[H], p[L], self._s):
            return 0
        return -1


class Thrusting(CandlestickPattern):
    """Bearish candle followed by a bullish that closes into the previous body
    but does not reach the midpoint. Bearish continuation.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("Thrusting", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p) or not is_bullish(c):
            return 0
        # Opens below previous close
        if c[O] >= p[C]:
            return 0
        # Closes within previous body but below midpoint
        pmid = body_midpoint(p)
        if c[C] <= p[C] or c[C] >= pmid:
            return 0
        return -1


class BearishSeparatingLines(CandlestickPattern):
    """Same open price, first bullish, second bearish — bearish continuation."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BearishSeparatingLines", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bullish(p) or not is_bearish(c):
            return 0
        if not _near(c[O], p[O], self._s):
            return 0
        return -1


class BullishSeparatingLines(CandlestickPattern):
    """Same open price, first bearish, second bullish — bullish continuation."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BullishSeparatingLines", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        if not is_bearish(p) or not is_bullish(c):
            return 0
        if not _near(c[O], p[O], self._s):
            return 0
        return 1


# ===================================================================
# 3. THREE-CANDLE PATTERNS  (period=3)
# ===================================================================


class MorningStar(CandlestickPattern):
    """Long bearish, small body (gap down), long bullish (gap up).

    Major bullish reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("MorningStar", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        # First: long bearish
        if not is_bearish(b1) or not _has_long_body(b1, self._s):
            return 0
        # Middle: small body (short or doji)
        if not _has_short_body(b2, self._s) and not _is_doji(b2, self._s):
            return 0
        # Middle gaps down from first
        if not _gaps_down(b2, b1):
            return 0
        # Third: long bullish, gaps up from middle
        if not is_bullish(b3) or not _has_long_body(b3, self._s):
            return 0
        if not _gaps_up(b3, b2):
            return 0
        return 1


class EveningStar(CandlestickPattern):
    """Long bullish, small body (gap up), long bearish (gap down).

    Major bearish reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("EveningStar", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not is_bullish(b1) or not _has_long_body(b1, self._s):
            return 0
        if not _has_short_body(b2, self._s) and not _is_doji(b2, self._s):
            return 0
        if not _gaps_up(b2, b1):
            return 0
        if not is_bearish(b3) or not _has_long_body(b3, self._s):
            return 0
        if not _gaps_down(b3, b2):
            return 0
        return -1


class MorningDojiStar(CandlestickPattern):
    """Same as MorningStar but middle candle is a Doji — stronger signal."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("MorningDojiStar", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not is_bearish(b1) or not _has_long_body(b1, self._s):
            return 0
        if not _is_doji(b2, self._s):
            return 0
        if not _gaps_down(b2, b1):
            return 0
        if not is_bullish(b3) or not _has_long_body(b3, self._s):
            return 0
        if not _gaps_up(b3, b2):
            return 0
        return 1


class EveningDojiStar(CandlestickPattern):
    """Same as EveningStar but middle candle is a Doji — stronger signal."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("EveningDojiStar", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not is_bullish(b1) or not _has_long_body(b1, self._s):
            return 0
        if not _is_doji(b2, self._s):
            return 0
        if not _gaps_up(b2, b1):
            return 0
        if not is_bearish(b3) or not _has_long_body(b3, self._s):
            return 0
        if not _gaps_down(b3, b2):
            return 0
        return -1


class BullishAbandonedBaby(CandlestickPattern):
    """Long bearish, doji with gap down, long bullish with gap up.

    Gap on BOTH sides of the doji — rare and strong reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BullishAbandonedBaby", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not is_bearish(b1) or not _is_doji(b2, self._s):
            return 0
        if not is_bullish(b3):
            return 0
        if b2[H] >= b1[L] or b3[L] <= b2[H]:
            return 0
        return 1


class BearishAbandonedBaby(CandlestickPattern):
    """Long bullish, doji with gap up, long bearish with gap down."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BearishAbandonedBaby", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not is_bullish(b1) or not _is_doji(b2, self._s):
            return 0
        if not is_bearish(b3):
            return 0
        if b2[L] <= b1[H] or b3[H] >= b2[L]:
            return 0
        return -1


class ThreeWhiteSoldiers(CandlestickPattern):
    """Three consecutive long bullish candles with higher closes.

    Strong bullish continuation.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ThreeWhiteSoldiers", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        for b in (b1, b2, b3):
            if not is_bullish(b) or not _has_long_body(b, self._s):
                return 0
        # Each should close higher than previous
        if not (b2[C] > b1[C] and b3[C] > b2[C]):
            return 0
        # Each should open within or near previous body
        if b2[O] <= b1[O] or b3[O] <= b2[O]:
            return 0
        return 1


class ThreeBlackCrows(CandlestickPattern):
    """Three consecutive long bearish candles with lower closes.

    Strong bearish continuation.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ThreeBlackCrows", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        for b in (b1, b2, b3):
            if not is_bearish(b) or not _has_long_body(b, self._s):
                return 0
        if not (b2[C] < b1[C] and b3[C] < b2[C]):
            return 0
        if b2[O] >= b1[O] or b3[O] >= b2[O]:
            return 0
        return -1


class ThreeInsideUp(CandlestickPattern):
    """Harami (bearish → doji/small inside) followed by a bullish confirming candle."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ThreeInsideUp", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not is_bearish(b1) or not _has_long_body(b1, self._s):
            return 0
        # Second candle inside first
        if not _inside(b2, b1):
            return 0
        # Third candle closes above first's close
        if not is_bullish(b3):
            return 0
        if b3[C] <= b1[C]:
            return 0
        return 1


class ThreeInsideDown(CandlestickPattern):
    """Harami (bullish → doji/small inside) followed by a bearish confirming candle."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ThreeInsideDown", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not is_bullish(b1) or not _has_long_body(b1, self._s):
            return 0
        if not _inside(b2, b1):
            return 0
        if not is_bearish(b3):
            return 0
        if b3[C] >= b1[C]:
            return 0
        return -1


class ThreeOutsideUp(CandlestickPattern):
    """Bullish Engulfing followed by a higher close confirming candle."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ThreeOutsideUp", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        # First: bearish, Second: bullish that engulfs first
        if not is_bearish(b1) or not is_bullish(b2):
            return 0
        if not _engulfs(b2, b1):
            return 0
        # Third: bullish and closes higher than second
        if not is_bullish(b3):
            return 0
        if b3[C] <= b2[C]:
            return 0
        return 1


class ThreeOutsideDown(CandlestickPattern):
    """Bearish Engulfing followed by a lower close confirming candle."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ThreeOutsideDown", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not is_bullish(b1) or not is_bearish(b2):
            return 0
        if not _engulfs(b2, b1):
            return 0
        if not is_bearish(b3):
            return 0
        if b3[C] >= b2[C]:
            return 0
        return -1


class TriStar(CandlestickPattern):
    """Three consecutive dojis — potential reversal.

    Bullish at bottom, bearish at top.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("TriStar", period=4)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not _is_doji(b1, self._s) or not _is_doji(b2, self._s) or not _is_doji(b3, self._s):
            return 0
        if _downtrend(window, 1):
            return 1
        if _uptrend(window, 1):
            return -1
        return 0


class UniqueThreeRiver(CandlestickPattern):
    """Long bearish, hammer-like (lower shadow), bullish confirming candle.

    Bullish reversal. Rare pattern.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("UniqueThreeRiver", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not is_bearish(b1) or not _has_long_body(b1, self._s):
            return 0
        # Second: bearish but with a long lower shadow and small body (hammer-like in downtrend)
        if not is_bearish(b2):
            return 0
        if not _has_short_body(b2, self._s):
            return 0
        if not _has_long_lower(b2, self._s):
            return 0
        # Third: bullish closes above second's body
        if not is_bullish(b3):
            return 0
        if b3[C] <= body_midpoint(b2):
            return 0
        return 1


class ThreeStarsInSouth(CandlestickPattern):
    """Three declining bearish candles with long lower shadows — bottoming pattern."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ThreeStarsInSouth", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        # All bearish
        for b in (b1, b2, b3):
            if not is_bearish(b):
                return 0
        # Each should have a lower shadow
        if not _has_long_lower(b1, self._s):
            return 0
        if not _has_long_lower(b2, self._s):
            return 0
        if not _has_long_lower(b3, self._s):
            return 0
        # Second inside first's body, third inside second's
        if not (b2[C] > b1[C] and b2[H] < b1[H]):
            return 0
        if not (b3[C] > b2[C] and b3[H] < b2[H]):
            return 0
        return 1


class AdvanceBlock(CandlestickPattern):
    """Three consecutive bullish candles, each with a higher close but
    showing weakening (long upper shadows, shrinking bodies).

    Bearish reversal signal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("AdvanceBlock", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        for b in (b1, b2, b3):
            if not is_bullish(b):
                return 0
        if not (b2[C] > b1[C] and b3[C] > b2[C]):
            return 0
        # Weakening signs: second and third have upper shadows, third's body is shorter
        if not _has_long_upper(b2, self._s) and not _has_long_upper(b3, self._s):
            return 0
        # Third body shorter than first
        if real_body(b3) >= real_body(b1):
            return 0
        return -1


class StalledPattern(CandlestickPattern):
    """Three bullish candles where the last two have small bodies and
    long upper shadows — stalling uptrend.

    Bearish reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("StalledPattern", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        for b in (b1, b2, b3):
            if not is_bullish(b):
                return 0
        if not (b2[C] > b1[C] and b3[C] > b2[C]):
            return 0
        # Last candle has a very small body and long upper shadow
        if not _has_short_body(b3, self._s):
            return 0
        if not _has_long_upper(b3, self._s):
            return 0
        return -1


class BullishTasukiGap(CandlestickPattern):
    """Gap up, then a bullish candle, then a bearish that opens in the gap
    but doesn't close it — bullish continuation.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BullishTasukiGap", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        # Upward gap between b1 and b2
        if not _gaps_up(b2, b1):
            return 0
        if not is_bullish(b2):
            return 0
        # Third: bearish, opens within the gap, doesn't close it
        if not is_bearish(b3):
            return 0
        if b3[O] <= b1[H] or b3[O] >= b2[L]:
            return 0
        if b3[C] <= b1[H]:
            return 0
        return 1


class BearishTasukiGap(CandlestickPattern):
    """Gap down, then a bearish candle, then a bullish that opens in the gap
    but doesn't close it — bearish continuation.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("BearishTasukiGap", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not _gaps_down(b2, b1):
            return 0
        if not is_bearish(b2):
            return 0
        if not is_bullish(b3):
            return 0
        if b3[O] >= b1[L] or b3[O] <= b2[H]:
            return 0
        if b3[C] >= b1[L]:
            return 0
        return -1


class GapSideBySideWhite(CandlestickPattern):
    """Gap up, two consecutive white candles at the gap level — continuation.

    Bullish: gap up + two white candles (bullish continuation).
    Bearish: gap down + two white candles inside the gap (bearish continuation).
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("GapSideBySideWhite", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        # Both b2 and b3 should be bullish
        if not is_bullish(b2) or not is_bullish(b3):
            return 0
        # Gap up: b2 gaps above b1
        if _gaps_up(b2, b1):
            # b3 should be at similar level as b2 (side by side)
            if _near(b3[O], b2[O], self._s) and _near(b3[C], b2[C], self._s):
                return 1
        # Gap down: b2 gaps below b1, bearish continuation
        if _gaps_down(b2, b1):
            if _near(b3[O], b2[O], self._s) and _near(b3[C], b2[C], self._s):
                return -1
        return 0


class UpDownGapThreeMethods(CandlestickPattern):
    """Three-bar pattern: gap up/down, continuation, then reversal — complex.

    Bullish: gap down, bearish, then bullish that closes the gap.
    Bearish: gap up, bullish, then bearish that closes the gap.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("UpDownGapThreeMethods", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        # Bearish version: gap up, then bullish, then bearish that closes gap
        if _gaps_up(b2, b1) and is_bullish(b1):
            if is_bullish(b2):
                if is_bearish(b3) and b3[C] <= b1[H]:
                    return -1
        # Bullish version: gap down, then bearish, then bullish that closes gap
        if _gaps_down(b2, b1) and is_bearish(b1):
            if is_bearish(b2):
                if is_bullish(b3) and b3[C] >= b1[L]:
                    return 1
        return 0


class ConcealingBabySwallow(CandlestickPattern):
    """Four candles: two long bearish, then two bearish that gap down
    with long shadows — bearish continuation (rare).
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("ConcealingBabySwallow", period=4)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if len(window) < 4:
            return 0
        b1, b2, b3, b4 = window[-4], window[-3], window[-2], window[-1]
        # C1 and C2: long black
        if not is_bearish(b1) or not is_bearish(b2):
            return 0
        if not _has_long_body(b1, self._s) or not _has_long_body(b2, self._s):
            return 0
        # C3: gaps down and opens with gap
        if not is_bearish(b3) or not _gaps_down(b3, b2):
            return 0
        # C4: opens even lower, closes inside C3's body
        if not is_bearish(b4):
            return 0
        if b4[O] >= b3[C] or b4[O] >= b3[O]:
            return 0
        if b4[C] <= b3[C]:
            return 0
        return -1


class LadderBottom(CandlestickPattern):
    """Five candles: four bearish descending, then a bullish that gaps up.

    Bullish reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("LadderBottom", period=5)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if len(window) < 5:
            return 0
        b1, b2, b3, b4, b5 = window[-5], window[-4], window[-3], window[-2], window[-1]
        # First four: bearish, each with lower close
        for i in range(3):
            if not is_bearish(window[-5 + i]):
                return 0
            if window[-4 + i][C] >= window[-5 + i][C]:
                return 0
        # C4: should have a long upper shadow
        if not _has_long_upper(b4, self._s):
            return 0
        # C5: bullish, gaps up
        if not is_bullish(b5):
            return 0
        if not _gaps_up(b5, b4):
            return 0
        return 1


class MatHold(CandlestickPattern):
    """Three white soldiers variation: long white, gap up small body, then
    two more long white. Bullish continuation.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("MatHold", period=5)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if len(window) < 5:
            return 0
        b1, b2, b3, b4, b5 = window[-5], window[-4], window[-3], window[-2], window[-1]
        # C1: long white
        if not is_bullish(b1) or not _has_long_body(b1, self._s):
            return 0
        # C2: small body (gap up from C1)
        if not _has_short_body(b2, self._s):
            return 0
        if not _gaps_up(b2, b1):
            return 0
        # C3, C4: long white continuing up
        if not is_bullish(b3) or not is_bullish(b4):
            return 0
        if not _has_long_body(b3, self._s) or not _has_long_body(b4, self._s):
            return 0
        if not (b3[C] > b2[C] and b4[C] > b3[C]):
            return 0
        # C5: long white with higher close
        if not is_bullish(b5) or not _has_long_body(b5, self._s):
            return 0
        if b5[C] <= b4[C]:
            return 0
        return 1


class RisingThreeMethods(CandlestickPattern):
    """Bullish continuation: long white, three small bearish inside, then long white."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("RisingThreeMethods", period=5)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if len(window) < 5:
            return 0
        b1, b2, b3, b4, b5 = window[-5], window[-4], window[-3], window[-2], window[-1]
        # C1: long white
        if not is_bullish(b1) or not _has_long_body(b1, self._s):
            return 0
        # C2-C4: three small bearish, each inside C1's price range
        for b in (b2, b3, b4):
            if not is_bearish(b):
                return 0
            if not _has_short_body(b, self._s):
                return 0
            if b[H] > b1[H] or b[L] < b1[L]:
                return 0
        # C5: long white above C1's high
        if not is_bullish(b5) or not _has_long_body(b5, self._s):
            return 0
        if b5[C] <= b1[H]:
            return 0
        return 1


class FallingThreeMethods(CandlestickPattern):
    """Bearish continuation: long black, three small bullish inside, then long black."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("FallingThreeMethods", period=5)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if len(window) < 5:
            return 0
        b1, b2, b3, b4, b5 = window[-5], window[-4], window[-3], window[-2], window[-1]
        if not is_bearish(b1) or not _has_long_body(b1, self._s):
            return 0
        for b in (b2, b3, b4):
            if not is_bullish(b):
                return 0
            if not _has_short_body(b, self._s):
                return 0
            if b[H] > b1[H] or b[L] < b1[L]:
                return 0
        if not is_bearish(b5) or not _has_long_body(b5, self._s):
            return 0
        if b5[C] >= b1[L]:
            return 0
        return -1


class Breakaway(CandlestickPattern):
    """Five-bar reversal pattern.

    Bullish: gap down, three small bearish, then a bullish that closes the gap.
    Bearish: gap up, three small bullish, then a bearish that closes the gap.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("Breakaway", period=5)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        if len(window) < 5:
            return 0
        b = window[-5:]
        # Bearish breakaway: gap up (C2), three small candles, then bearish closes gap
        if is_bullish(b[0]) and _gaps_up(b[1], b[0]):
            if all(is_bullish(x) or _has_short_body(x, self._s) for x in b[1:4]):
                if is_bearish(b[4]) and b[4][C] <= b[0][H]:
                    return -1
        # Bullish breakaway: gap down (C2), three small candles, then bullish closes gap
        if is_bearish(b[0]) and _gaps_down(b[1], b[0]):
            if all(is_bearish(x) or _has_short_body(x, self._s) for x in b[1:4]):
                if is_bullish(b[4]) and b[4][C] >= b[0][L]:
                    return 1
        return 0


class StickSandwich(CandlestickPattern):
    """Bearish, bullish, bearish where the two bearish have the same close.

    Bullish reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("StickSandwich", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        if not is_bearish(b1) or not is_bullish(b2) or not is_bearish(b3):
            return 0
        if not _near(b3[C], b1[C], self._s):
            return 0
        return 1


class IdenticalThreeCrows(CandlestickPattern):
    """Three consecutive long black candles, each closing around the same low.

    Bearish continuation (strong).
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("IdenticalThreeCrows", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        for b in (b1, b2, b3):
            if not is_bearish(b) or not _has_long_body(b, self._s):
                return 0
        if not (b2[C] < b1[C] and b3[C] < b2[C]):
            return 0
        # Each close should be near the day's low
        for b in (b1, b2, b3):
            if not _near(b[C], b[L], self._s):
                return 0
        # All three closes should be similar
        if not _near(b3[C], b1[C], self._s):
            return 0
        return -1


class TwoCrows(CandlestickPattern):
    """Long white, gap up black, then black that opens above and closes below
    the first candle — bearish reversal.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("TwoCrows", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        # C1: long white
        if not is_bullish(b1) or not _has_long_body(b1, self._s):
            return 0
        # C2: gap up, black (but not engulfing C1)
        if not is_bearish(b2):
            return 0
        if not _gaps_up(b2, b1):
            return 0
        if _engulfs(b2, b1):
            return 0
        # C3: opens above C2, closes below C1 midpoint — bearish
        if not is_bearish(b3):
            return 0
        if b3[O] <= b2[O]:
            return 0
        if b3[C] >= body_midpoint(b1):
            return 0
        return -1


class UpsideGapTwoCrows(CandlestickPattern):
    """Gap up, then two black candles inside the gap — bearish reversal."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("UpsideGapTwoCrows", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        # C1: white candle
        if not is_bullish(b1):
            return 0
        # Gap up to C2
        if not _gaps_up(b2, b1):
            return 0
        # C2 and C3: both black
        if not is_bearish(b2) or not is_bearish(b3):
            return 0
        # C3 opens above C2, closes below C2
        if b3[O] <= b2[O]:
            return 0
        if b3[C] >= b2[C]:
            return 0
        # C3 still above C1's high (gap not fully closed)
        if b3[C] <= b1[H]:
            return 0
        return -1


class Kicking(CandlestickPattern):
    """Opposite Marubozus with a gap between them — dramatic reversal.

    Bullish: bearish Marubozu, gap down, then bullish Marubozu.
    Bearish: bullish Marubozu, gap up, then bearish Marubozu.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("Kicking", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        p, c = window[-2], window[-1]
        # Both must be Marubozu-like
        if not _has_long_body(p, self._s):
            return 0
        if not _has_long_body(c, self._s):
            return 0
        if not _has_short_upper(p, self._s) or not _has_short_lower(p, self._s):
            return 0
        if not _has_short_upper(c, self._s) or not _has_short_lower(c, self._s):
            return 0
        # Bullish: bearish then bullish with gap up
        if is_bearish(p) and is_bullish(c):
            return 1 if _gaps_up(c, p) else 0
        # Bearish: bullish then bearish with gap down
        if is_bullish(p) and is_bearish(c):
            return -1 if _gaps_down(c, p) else 0
        return 0


class KickingByLength(CandlestickPattern):
    """Like Kicking but also requires the gap to be a significant percentage."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("KickingByLength", period=2)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        base = Kicking(self._s)
        base.window = list(window)
        base._is_ready = True
        signal = base.compute_next_value(window)
        if signal == 0:
            return 0
        p, c = window[-2], window[-1]
        # Require the body to be a certain % of range
        if _body_pct(p) < 0.5 or _body_pct(c) < 0.5:
            return 0
        return signal


class Hikkake(CandlestickPattern):
    """Inside bar followed by a breakout in the opposite direction.

    Bullish: inside bar (lower high, higher low), then bearish below inside low,
    then next bar above inside high.
    Bearish: inside bar, then bullish above inside high, then next below inside low.
    """

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("Hikkake", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        # B2 is inside B1 (lower high, higher low)
        if not (b2[H] < b1[H] and b2[L] > b1[L]):
            return 0
        # Bullish Hikkake: B3 makes a lower low (breakdown trap) then reverses
        # Actually: B3 below B2's low triggers the bear trap, then reversal
        # More common: B3 closes below B2's low
        if b3[C] < b2[L] and is_bullish(b3):
            return 1
        # Bearish Hikkake: B3 above B2's high triggers bull trap
        if b3[C] > b2[H] and is_bearish(b3):
            return -1
        return 0


class HikkakeModified(CandlestickPattern):
    """Modified Hikkake that uses body ranges instead of full candle ranges."""

    def __init__(self, settings: Optional[CandleSettings] = None) -> None:
        super().__init__("HikkakeModified", period=3)
        self._s = settings or CandleSettings()

    def compute_next_value(self, window: list[tuple]) -> int:
        b1, b2, b3 = window[-3], window[-2], window[-1]
        # B2 body inside B1 body
        if not _inside(b2, b1):
            return 0
        # Bullish: B3 closes below B2 body low then rallies
        if b3[C] < min(b2[O], b2[C]):
            return 1
        # Bearish: B3 closes above B2 body high then falls
        if b3[C] > max(b2[O], b2[C]):
            return -1
        return 0
