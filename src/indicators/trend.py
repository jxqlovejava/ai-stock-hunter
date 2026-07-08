# -*- coding: utf-8 -*-
"""Trend-following indicators.

HullMovingAverage      — lag-optimised WMA combination
KaufmanAdaptiveMovingAverage — volatility-based adaptive EMA
IchimokuKinkoHyo       — 5-line Japanese cloud system
SuperTrend             — ATR-based trailing stop
ParabolicSAR           — acceleration-factor trailing stop
DonchianChannel        — period highest-high / lowest-low
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .base import BarIndicator, CandleSettings, Indicator, WindowIndicator

# ===================================================================
# Hull Moving Average
# ===================================================================


class HullMovingAverage(WindowIndicator):
    """Hull Moving Average — nearly lag-free smoothed moving average.

    Formula:
        HMA = WMA(2 * WMA(n/2) - WMA(n), sqrt(n))

    Reference: Alan Hull, 2005.
    """

    def __init__(self, period: int = 20) -> None:
        super().__init__(period)
        self.name = f"HMA({period})"

    @staticmethod
    def _wma(values: np.ndarray) -> float:
        n = len(values)
        weights = np.arange(1, n + 1, dtype=float)
        return float(np.dot(values, weights) / weights.sum())

    def compute_next_value(self, window: list[float]) -> float:
        arr = np.array(window, dtype=float)
        n = len(arr)
        sqrt_n = max(2, int(math.sqrt(n)))

        wma_half = self._wma(arr[-n // 2 :]) if n // 2 >= 2 else arr[-1]
        wma_full = self._wma(arr)

        raw = 2.0 * wma_half - wma_full
        # Build a mini-window of sqrt_n for the outer WMA
        # We approximate by just doing WMA of the raw value with previous
        # but since this is stateful, we maintain a secondary rolling buffer
        if not hasattr(self, "_hma_buffer"):
            self._hma_buffer = []
        self._hma_buffer.append(raw)
        if len(self._hma_buffer) > sqrt_n:
            self._hma_buffer.pop(0)

        if len(self._hma_buffer) >= sqrt_n:
            return self._wma(np.array(self._hma_buffer, dtype=float))
        return raw

    def reset(self) -> None:
        super().reset()
        self._hma_buffer = []


# ===================================================================
# Kaufman Adaptive Moving Average
# ===================================================================


class KaufmanAdaptiveMovingAverage(WindowIndicator):
    """KAMA — volatility-based adaptive EMA.

    Fast EMA when trending, slow EMA when choppy.
    Uses Efficiency Ratio (ER) to modulate the smoothing constant.
    """

    def __init__(self, period: int = 10, fast: int = 2, slow: int = 30) -> None:
        super().__init__(period + 1)  # +1 for the delta reference
        self._er_period = period
        self.fast = fast
        self.slow = slow
        self.name = f"KAMA({period},{fast},{slow})"
        self._kama: Optional[float] = None

    def compute_next_value(self, window: list[float]) -> float:
        if self._kama is None:
            self._kama = window[-1]
            return self._kama

        # Efficiency Ratio
        change = abs(window[-1] - window[-self._er_period]) if len(window) > self._er_period else 0.0
        volatility = sum(abs(window[i] - window[i - 1]) for i in range(1, len(window)))
        er = change / volatility if volatility > 0 else 0.0

        # Smoothing constant
        fast_sc = 2.0 / (self.fast + 1.0)
        slow_sc = 2.0 / (self.slow + 1.0)
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

        self._kama = self._kama + sc * (window[-1] - self._kama)
        return self._kama

    def reset(self) -> None:
        super().reset()
        self._kama = None


# ===================================================================
# Ichimoku Kinko Hyo
# ===================================================================


@dataclass
class IchimokuLines:
    """Output of the Ichimoku indicator."""

    tenkan_sen: float       # conversion line
    kijun_sen: float        # base line
    senkou_span_a: float    # leading span A
    senkou_span_b: float    # leading span B
    chikou_span: float      # lagging span


class IchimokuKinkoHyo(Indicator):
    """Ichimoku Kinko Hyo — 5-line cloud system.

    Ignores the bar format and works on raw high/low/close arrays
    passed via ``update(high, low, close)``.
    """

    def __init__(
        self,
        tenkan_period: int = 9,
        kijun_period: int = 26,
        senkou_b_period: int = 52,
        displacement: int = 26,
    ) -> None:
        super().__init__()
        self.tenkan_period = tenkan_period
        self.kijun_period = kijun_period
        self.senkou_b_period = senkou_b_period
        self.displacement = displacement
        self.name = f"Ichimoku({tenkan_period},{kijun_period},{senkou_b_period})"

        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

        # Warmup needed = max period + displacement
        self._warmup = max(tenkan_period, kijun_period, senkou_b_period) + displacement

    def update(self, high: float, low: float, close: float) -> None:  # type: ignore[override]
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)

        if len(self._highs) >= self._warmup:
            self._is_ready = True
            self._current_value = self._compute()

    def _donchian(self, period: int) -> float:
        """Midpoint of highest high and lowest low over period."""
        hh = max(self._highs[-period:])
        ll = min(self._lows[-period:])
        return (hh + ll) / 2.0

    def _compute(self) -> IchimokuLines:
        h = self._highs
        l = self._lows
        c = self._closes

        tenkan = self._donchian(self.tenkan_period)
        kijun = self._donchian(self.kijun_period)

        # Senkou A: (tenkan + kijun) / 2 shifted forward
        senkou_a = (tenkan + kijun) / 2.0

        # Senkou B: donchian of senkou_b_period shifted forward
        senkou_b = self._donchian(self.senkou_b_period)

        # Chikou: current close shifted backward (lagging span)
        chikou_idx = -self.displacement
        chikou = c[chikou_idx] if abs(chikou_idx) <= len(c) else c[-1]

        return IchimokuLines(
            tenkan_sen=tenkan,
            kijun_sen=kijun,
            senkou_span_a=senkou_a,
            senkou_span_b=senkou_b,
            chikou_span=chikou,
        )

    def reset(self) -> None:
        super().reset()
        self._highs.clear()
        self._lows.clear()
        self._closes.clear()


# ===================================================================
# SuperTrend
# ===================================================================


@dataclass
class SuperTrendValue:
    """SuperTrend output."""

    basic_upper: float
    basic_lower: float
    final_upper: float
    final_lower: float
    supertrend: float
    direction: int  # +1 up, -1 down


class SuperTrend(Indicator):
    """ATR-based trailing stop indicator.

    Works on bar data passed via ``update(high, low, close)``.
    """

    def __init__(self, atr_period: int = 10, multiplier: float = 3.0) -> None:
        super().__init__()
        self.atr_period = atr_period
        self.multiplier = multiplier
        self.name = f"SuperTrend({atr_period},{multiplier})"

        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

        self._atr: Optional[float] = None
        self._final_upper: Optional[float] = None
        self._final_lower: Optional[float] = None
        self._direction: int = 1

    def update(self, high: float, low: float, close: float) -> None:  # type: ignore[override]
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)

        if len(self._closes) < 2:
            return

        self._is_ready = True
        self._current_value = self._compute()

    def _tr(self, i: int) -> float:
        h, l, pc = self._highs[i], self._lows[i], self._closes[i - 1]
        return max(h - l, abs(h - pc), abs(l - pc))

    def _compute(self) -> SuperTrendValue:
        n = len(self._closes)
        h, l, c = self._highs[n - 1], self._lows[n - 1], self._closes[n - 1]

        # ATR
        if self._atr is None:
            tr_list = [self._tr(i) for i in range(1, n)]
            self._atr = sum(tr_list) / max(len(tr_list), 1)
        else:
            tr = self._tr(n - 1)
            self._atr = (self._atr * (self.atr_period - 1) + tr) / self.atr_period

        basic_upper = (h + l) / 2.0 + self.multiplier * self._atr
        basic_lower = (h + l) / 2.0 - self.multiplier * self._atr

        # Final bands
        final_upper = basic_upper if self._final_upper is None else (
            basic_upper if basic_upper < self._final_upper or c > self._final_upper
            else self._final_upper
        )
        final_lower = basic_lower if self._final_lower is None else (
            basic_lower if basic_lower > self._final_lower or c < self._final_lower
            else self._final_lower
        )

        # Direction
        prev_direction = self._direction
        if c <= final_upper if prev_direction == -1 else c < final_upper:
            new_direction = -1
        else:
            new_direction = 1

        supertrend = final_upper if new_direction == -1 else final_lower

        if new_direction != prev_direction:
            # On reversal, swap bands
            final_upper, final_lower = final_lower, final_upper

        self._final_upper = final_upper
        self._final_lower = final_lower
        self._direction = new_direction

        return SuperTrendValue(
            basic_upper=basic_upper,
            basic_lower=basic_lower,
            final_upper=final_upper,
            final_lower=final_lower,
            supertrend=supertrend,
            direction=new_direction,
        )

    def reset(self) -> None:
        super().reset()
        self._highs.clear()
        self._lows.clear()
        self._closes.clear()
        self._atr = None
        self._final_upper = None
        self._final_lower = None
        self._direction = 1


# ===================================================================
# Parabolic SAR
# ===================================================================


class ParabolicSAR(Indicator):
    """Parabolic Stop and Reverse — acceleration-factor trailing stop.

    Works on bar data passed via ``update(high, low)``.
    """

    def __init__(self, acceleration: float = 0.02, max_acceleration: float = 0.20) -> None:
        super().__init__()
        self.acceleration = acceleration
        self.max_acceleration = max_acceleration
        self.name = f"ParabolicSAR({acceleration},{max_acceleration})"

        self._highs: list[float] = []
        self._lows: list[float] = []

        self._sar: Optional[float] = None
        self._ep: Optional[float] = None  # extreme point
        self._af: float = acceleration
        self._is_long: bool = True

    def update(self, high: float, low: float) -> None:  # type: ignore[override]
        self._highs.append(high)
        self._lows.append(low)

        if len(self._highs) < 2:
            if len(self._highs) == 1:
                self._sar = low
                self._ep = high
            return

        self._is_ready = True
        self._current_value = self._compute()

    def _compute(self) -> float:
        h, l = self._highs[-1], self._lows[-1]
        prev_h, prev_l = self._highs[-2], self._lows[-2]

        if self._sar is None:
            self._sar = prev_l if self._is_long else prev_h
            self._ep = prev_h if self._is_long else prev_l

        prev_sar = self._sar

        if self._is_long:
            self._sar = prev_sar + self._af * (self._ep - prev_sar)
            # SAR cannot exceed prior two lows
            self._sar = min(self._sar, prev_l, self._lows[-3] if len(self._highs) >= 3 else prev_l)
            if l < self._sar:
                # Switch to short
                self._is_long = False
                self._sar = self._ep
                self._ep = h
                self._af = self.acceleration
            else:
                if h > self._ep:
                    self._ep = h
                    self._af = min(self._af + self.acceleration, self.max_acceleration)
        else:
            self._sar = prev_sar - self._af * (prev_sar - self._ep)
            self._sar = max(self._sar, prev_h, self._highs[-3] if len(self._highs) >= 3 else prev_h)
            if h > self._sar:
                self._is_long = True
                self._sar = self._ep
                self._ep = l
                self._af = self.acceleration
            else:
                if l < self._ep:
                    self._ep = l
                    self._af = min(self._af + self.acceleration, self.max_acceleration)

        return self._sar

    def reset(self) -> None:
        super().reset()
        self._highs.clear()
        self._lows.clear()
        self._sar = None
        self._ep = None
        self._af = self.acceleration
        self._is_long = True


# ===================================================================
# Donchian Channel
# ===================================================================


@dataclass
class DonchianChannelValue:
    """Donchian Channel output."""

    upper: float
    middle: float
    lower: float


class DonchianChannel(BarIndicator):
    """Period-based highest high, lowest low, and midpoint."""

    def __init__(self, period: int = 20) -> None:
        super().__init__(period)
        self.name = f"Donchian({period})"

    def compute_next_value(self, window: list[tuple]) -> DonchianChannelValue:
        highs = [b[1] for b in window]
        lows = [b[2] for b in window]
        upper = max(highs)
        lower = min(lows)
        return DonchianChannelValue(
            upper=upper,
            middle=(upper + lower) / 2.0,
            lower=lower,
        )
