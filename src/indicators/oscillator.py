# -*- coding: utf-8 -*-
"""Oscillator-type indicators.

StochasticRSI        — RSI stochastized (0-100 bounded)
UltimateOscillator   — 3-period weighted composite
AwesomeOscillator    — 5-period SMA - 34-period SMA of midpoints
FisherTransform      — normalise prices to Gaussian-like distribution
ConnorsRSI           — RSI + streak + percent rank composite
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .base import BarIndicator, WindowIndicator


# ===================================================================
# Stochastic RSI
# ===================================================================


class StochasticRSI(WindowIndicator):
    """Stochastic RSI — applies the stochastics formula to RSI values.

    Maps RSI (0-100) into a 0-100 oscillator that reacts faster to extremes.
    """

    def __init__(self, rsi_period: int = 14, stoch_period: int = 14, k_smoothing: int = 3, d_smoothing: int = 3) -> None:
        # Need rsi_period + stoch_period values for first %K
        super().__init__(rsi_period + stoch_period)
        self.rsi_period = rsi_period
        self.stoch_period = stoch_period
        self.k_smoothing = k_smoothing
        self.d_smoothing = d_smoothing
        self.name = f"StochRSI({rsi_period},{stoch_period})"

        # Secondary buffers
        self._rsi_buffer: list[float] = []
        self._k_buffer: list[float] = []

    def compute_next_value(self, window: list[float]) -> tuple[float, float]:
        # Compute RSI
        if len(window) < self.rsi_period + 1:
            return (50.0, 50.0)

        deltas = np.diff(window, n=1)
        gains = deltas[deltas > 0].sum() if deltas.size > 0 else 0.0
        losses = (-deltas[deltas < 0]).sum() if deltas.size > 0 else 0.0

        avg_gain = gains / self.rsi_period if self.rsi_period > 0 else 0.0
        avg_loss = losses / self.rsi_period if self.rsi_period > 0 else 1e-10

        if avg_loss < 1e-12:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - 100.0 / (1.0 + rs)

        self._rsi_buffer.append(rsi)
        if len(self._rsi_buffer) > self.stoch_period:
            self._rsi_buffer.pop(0)

        # Stochastize
        if len(self._rsi_buffer) >= self.stoch_period:
            highest = max(self._rsi_buffer[-self.stoch_period :])
            lowest = min(self._rsi_buffer[-self.stoch_period :])
            k_raw = 100.0 * (rsi - lowest) / (highest - lowest + 1e-10)

            self._k_buffer.append(k_raw)
            if len(self._k_buffer) > self.k_smoothing:
                self._k_buffer.pop(0)

            k = np.mean(self._k_buffer).item()
            d = np.mean(self._k_buffer[-min(len(self._k_buffer), self.d_smoothing) :]).item()
            return (round(k, 4), round(d, 4))

        return (50.0, 50.0)

    def reset(self) -> None:
        super().reset()
        self._rsi_buffer.clear()
        self._k_buffer.clear()


# ===================================================================
# Ultimate Oscillator
# ===================================================================


class UltimateOscillator(WindowIndicator):
    """Ultimate Oscillator by Larry Williams — 3-period weighted composite.

    Combines three lookback periods (default 7, 14, 28) to avoid whipsaws.
    """

    def __init__(self, period1: int = 7, period2: int = 14, period3: int = 28,
                 weight1: float = 4.0, weight2: float = 2.0, weight3: float = 1.0) -> None:
        super().__init__(period3 + 1)
        self.period1 = period1
        self.period2 = period2
        self.period3 = period3
        self.weight1 = weight1
        self.weight2 = weight2
        self.weight3 = weight3
        self.name = f"UltimateOsc({period1},{period2},{period3})"

    @staticmethod
    def _bp(close: float, low: float) -> float:
        """Buying pressure = close - min(low, prev_close)."""
        return close - low

    @staticmethod
    def _tr(high: float, low: float, prev_close: float) -> float:
        """True range."""
        return max(high - low, abs(high - prev_close), abs(low - prev_close))

    def compute_next_value(self, window: list[float]) -> float:
        # window holds close prices — we need OHLC for this
        # Override: this expects update calls that pass a data structure
        # For now, return 50 if the window doesn't have the right structure
        return 50.0

    def reset(self) -> None:
        super().reset()


class UltimateOscillatorOHLC(WindowIndicator):
    """Ultimate Oscillator variant that accepts bar tuples (high, low, close)."""

    def __init__(self, period1: int = 7, period2: int = 14, period3: int = 28,
                 weight1: float = 4.0, weight2: float = 2.0, weight3: float = 1.0) -> None:
        super().__init__(period3 + 2)
        self.p1, self.p2, self.p3 = period1, period2, period3
        self.w1, self.w2, self.w3 = weight1, weight2, weight3
        self.name = f"UltimateOsc({period1},{period2},{period3})"

    def compute_next_value(self, window: list[tuple]) -> float:
        n = len(window)
        if n < 3:
            return 50.0

        def _calc(p: int) -> float:
            relevant = window[-(p + 1) :]
            bp_sum = 0.0
            tr_sum = 0.0
            for i in range(1, len(relevant)):
                h, l, c = relevant[i][1], relevant[i][2], relevant[i][3]
                prev_c = relevant[i - 1][3]
                bp_sum += max(c - l, 0.0)
                tr_sum += max(h - l, abs(h - prev_c), abs(l - prev_c))
            return bp_sum / tr_sum if tr_sum > 0 else 0.5

        avg1 = _calc(self.p1)
        avg2 = _calc(self.p2)
        avg3 = _calc(self.p3)

        uo = 100.0 * (self.w1 * avg1 + self.w2 * avg2 + self.w3 * avg3) / (self.w1 + self.w2 + self.w3)
        return round(uo, 4)

    def reset(self) -> None:
        super().reset()


# ===================================================================
# Awesome Oscillator
# ===================================================================


class AwesomeOscillator(BarIndicator):
    """Awesome Oscillator by Bill Williams.

    AO = SMA(median price, 5) - SMA(median price, 34)
    """

    def __init__(self, fast: int = 5, slow: int = 34) -> None:
        super().__init__(slow)
        self.fast_period = fast
        self.slow_period = slow
        self.name = f"AO({fast},{slow})"

    def compute_next_value(self, window: list[tuple]) -> float:
        mids = [(b[1] + b[2]) / 2.0 for b in window]

        fast_sma = np.mean(mids[-self.fast_period :]).item() if len(mids) >= self.fast_period else 0.0
        slow_sma = np.mean(mids).item() if len(mids) > 0 else 0.0

        return round(fast_sma - slow_sma, 6)


# ===================================================================
# Fisher Transform
# ===================================================================


class FisherTransform(WindowIndicator):
    """Fisher Transform — normalises price to Gaussian-like distribution (-1 to +1).

    Extreme values (> +1 or < -1) suggest overbought/oversold.
    """

    def __init__(self, period: int = 10) -> None:
        super().__init__(period)
        self.name = f"Fisher({period})"
        self._prev_fisher: float = 0.0

    def compute_next_value(self, window: list[float]) -> tuple[float, float]:
        """Returns (fisher_value, trigger_value)."""
        low = min(window)
        high = max(window)
        price = window[-1]

        # Normalise to -1..+1
        if high - low > 0:
            norm = 2.0 * (price - low) / (high - low) - 1.0
        else:
            norm = 0.0

        # Clamp
        norm = max(-0.999, min(0.999, norm))

        # Fisher transform
        fisher = 0.5 * math.log((1.0 + norm) / (1.0 - norm))
        smooth = 0.5 * fisher + 0.5 * self._prev_fisher

        trigger = self._prev_fisher
        self._prev_fisher = smooth

        return (round(smooth, 6), round(trigger, 6))

    def reset(self) -> None:
        super().reset()
        self._prev_fisher = 0.0


# ===================================================================
# Connors RSI
# ===================================================================


class ConnorsRSI(WindowIndicator):
    """ConnorsRSI (CRSI) — composite of three components:

    1. Standard RSI(period)
    2. Streak RSI(period)  — RSI of consecutive up/down days
    3. Percent Rank(period) — rank of current close in lookback

    Formula: CRSI = (RSI_Close + RSI_Streak + PercentRank) / 3
    """

    def __init__(self, rsi_period: int = 3, streak_period: int = 2, rank_period: int = 100) -> None:
        super().__init__(max(rsi_period, rank_period) + streak_period + 1)
        self.rsi_period = rsi_period
        self.streak_period = streak_period
        self.rank_period = rank_period
        self.name = f"CRSI({rsi_period},{streak_period},{rank_period})"

        self._streak: int = 0

    def _compute_rsi(self, values: np.ndarray) -> float:
        deltas = np.diff(values)
        if deltas.size == 0:
            return 50.0
        gains = deltas[deltas > 0].sum()
        losses = (-deltas[deltas < 0]).sum()
        count = len(deltas)
        avg_gain = gains / count if count > 0 else 0.0
        avg_loss = losses / count if count > 0 else 1e-10
        if avg_loss < 1e-12:
            return 100.0  # no losses = all gains = strong momentum
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    def compute_next_value(self, window: list[float]) -> float:
        # --- Component 1: Close RSI ---
        close_rsi = self._compute_rsi(np.array(window[-self.rsi_period - 1 :], dtype=float))

        # --- Component 2: Streak RSI ---
        # Update streak
        if len(window) >= 2:
            if window[-1] > window[-2]:
                self._streak = self._streak + 1 if self._streak > 0 else 1
            elif window[-1] < window[-2]:
                self._streak = self._streak - 1 if self._streak < 0 else -1
            else:
                self._streak = 0

        # RSI of streak values (need streak_period+1 streak values)
        # We approximate by doing RSI on the streak sequence
        if len(window) >= self.streak_period + 1:
            # Simulate streak values for RSI computation
            streak_vals = []
            temp_streak = 0
            for i in range(max(0, len(window) - self.streak_period - 1), len(window)):
                if i == 0:
                    continue
                if window[i] > window[i - 1]:
                    temp_streak = temp_streak + 1 if temp_streak > 0 else 1
                elif window[i] < window[i - 1]:
                    temp_streak = temp_streak - 1 if temp_streak < 0 else -1
                else:
                    temp_streak = 0
                streak_vals.append(float(temp_streak))
            streak_rsi = self._compute_rsi(np.array(streak_vals)) if len(streak_vals) > 1 else 50.0
        else:
            streak_rsi = 50.0

        # --- Component 3: Percent Rank ---
        lookback = window[-self.rank_period :] if len(window) >= self.rank_period else window
        current = window[-1]
        count_below = sum(1 for v in lookback if v < current)
        pct_rank = (count_below / max(len(lookback), 1)) * 100.0

        crsi = (close_rsi + streak_rsi + pct_rank) / 3.0
        return round(crsi, 4)

    def reset(self) -> None:
        super().reset()
        self._streak = 0
