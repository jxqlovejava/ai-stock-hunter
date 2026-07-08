# -*- coding: utf-8 -*-
"""Volatility and volume-based indicators.

KeltnerChannels     — EMA ± k × ATR channel
ChoppinessIndex     — market chop vs trend (0-100)
ForceIndex          — volume-weighted price change
ChaikinMoneyFlow    — volume-weighted accumulation/distribution
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .base import BarIndicator, CandleSettings, Indicator, WindowIndicator


# ===================================================================
# Keltner Channels
# ===================================================================


@dataclass
class KeltnerChannelValue:
    """Keltner Channel output."""

    middle: float
    upper: float
    lower: float
    bandwidth: float  # (upper - lower) / middle * 100


class KeltnerChannels(Indicator):
    """Keltner Channels — EMA with ATR-based bands.

    Uses bar data passed via ``update(high, low, close)`` or
    ``update_bar(open, high, low, close)``.
    """

    def __init__(self, ema_period: int = 20, atr_period: int = 10, multiplier: float = 2.0, ema: Optional[float] = None) -> None:
        super().__init__()
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.multiplier = multiplier
        self.name = f"Keltner({ema_period},{atr_period},{multiplier})"

        self._closes: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []

        self._ema: Optional[float] = ema
        self._atr: Optional[float] = None

    def update(self, high: float, low: float, close: float) -> None:  # type: ignore[override]
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)

        if len(self._closes) < 2:
            if len(self._closes) == 1:
                self._ema = close
            return

        self._is_ready = True
        self._current_value = self._compute(close)

    def _tr(self, i: int) -> float:
        h, l, pc = self._highs[i], self._lows[i], self._closes[i - 1]
        return max(h - l, abs(h - pc), abs(l - pc))

    def _compute(self, close: float) -> KeltnerChannelValue:
        n = len(self._closes)

        # EMA
        k = 2.0 / (self.ema_period + 1.0)
        self._ema = close if self._ema is None else close * k + self._ema * (1.0 - k)

        # ATR
        if self._atr is None:
            tr_list = [self._tr(i) for i in range(1, n)]
            self._atr = sum(tr_list) / max(len(tr_list), 1)
        else:
            tr = self._tr(n - 1)
            self._atr = (self._atr * (self.atr_period - 1) + tr) / self.atr_period

        upper = self._ema + self.multiplier * self._atr
        lower = self._ema - self.multiplier * self._atr
        bandwidth = ((upper - lower) / max(abs(self._ema), 1e-12)) * 100.0

        return KeltnerChannelValue(
            middle=round(self._ema, 6),
            upper=round(upper, 6),
            lower=round(lower, 6),
            bandwidth=round(bandwidth, 4),
        )

    def reset(self) -> None:
        super().reset()
        self._closes.clear()
        self._highs.clear()
        self._lows.clear()
        self._ema = None
        self._atr = None


# ===================================================================
# Choppiness Index
# ===================================================================


class ChoppinessIndex(BarIndicator):
    """Choppiness Index by E.W. Dreiss — measures market chop vs trending.

    CI = 100 × log10( sum(TR, n) / (highest_high - lowest_low, n) ) / log10(n)

    0-100: lower values = trending, higher values = choppy.
    Threshold: < 38.2 trending, > 61.8 choppy.
    """

    def __init__(self, period: int = 14) -> None:
        super().__init__(period + 1)
        self.period = period
        self.name = f"Choppiness({period})"

    def compute_next_value(self, window: list[tuple]) -> float:
        n = min(len(window), self.period)
        if n < 2:
            return 50.0

        # True Range sum
        tr_sum = 0.0
        for i in range(-n, 0):
            h, l = window[i][1], window[i][2]
            prev_c = window[i - 1][3] if i > -len(window) else window[i][3]
            tr_sum += max(h - l, abs(h - prev_c), abs(l - prev_c))

        # Highest high / lowest low
        relevant = window[-n:]
        highest = max(b[1] for b in relevant)
        lowest = min(b[2] for b in relevant)

        if highest - lowest <= 0 or tr_sum <= 0:
            return 50.0

        ci = 100.0 * math.log10(tr_sum / (highest - lowest)) / math.log10(n)
        return round(max(0.0, min(100.0, ci)), 4)

    def reset(self) -> None:
        super().reset()


# ===================================================================
# Force Index
# ===================================================================


class ForceIndex(WindowIndicator):
    """Force Index by Alexander Elder — volume-weighted price change.

    FI(1) = (close_t - close_t-1) × volume_t
    FI(N) = EMA of FI(1) over N periods
    """

    def __init__(self, period: int = 13) -> None:
        super().__init__(period)
        self.period = period
        self.name = f"ForceIndex({period})"
        self._raw: list[float] = []
        self._prev_close: Optional[float] = None

    def compute_next_value(self, window: list[float]) -> float:
        # window holds raw ForceIndex(1) values
        return np.mean(window).item()

    def update(self, close: float, volume: float) -> None:  # type: ignore[override]
        if self._prev_close is not None:
            raw_fi = (close - self._prev_close) * volume
            self._raw.append(raw_fi)
            if len(self._raw) > self.period:
                self._raw.pop(0)
            if len(self._raw) >= self.period:
                self._is_ready = True
                self._current_value = self.compute_next_value(list(self._raw))
        self._prev_close = close

    def reset(self) -> None:
        super().reset()
        self._raw.clear()
        self._prev_close = None


# ===================================================================
# Chaikin Money Flow
# ===================================================================


class ChaikinMoneyFlow(BarIndicator):
    """Chaikin Money Flow by Marc Chaikin.

    CMF = sum(AD × volume, N) / sum(volume, N)
    AD = (close - low) - (high - close) / (high - low)

    Positive = buying pressure, Negative = selling pressure.
    """

    def __init__(self, period: int = 21) -> None:
        super().__init__(period)
        self.period = period
        self.name = f"CMF({period})"

    @staticmethod
    def _ad(bar: tuple) -> float:
        h, l, c = bar[1], bar[2], bar[3]
        rng = h - l
        if rng == 0:
            return 0.0
        mfm = ((c - l) - (h - c)) / rng
        return mfm * bar[4] if len(bar) > 4 else mfm

    def compute_next_value(self, window: list[tuple]) -> float:
        ad_sum = 0.0
        vol_sum = 0.0
        for b in window:
            ad = self._ad(b)
            vol = b[4] if len(b) > 4 else 1.0
            ad_sum += ad
            vol_sum += vol

        cmf = ad_sum / vol_sum if vol_sum > 0 else 0.0
        return round(cmf, 6)

    def reset(self) -> None:
        super().reset()
