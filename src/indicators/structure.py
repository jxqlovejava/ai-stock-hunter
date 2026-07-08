# -*- coding: utf-8 -*-
"""Market structure indicators.

HurstExponent  — R/S analysis to detect trending vs mean-reverting regimes
ZigZag         — Percentage-threshold swing detection
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from numpy.polynomial import polynomial as P

from .base import BarIndicator, CandleSettings, WindowIndicator


# ===================================================================
# Hurst Exponent (R/S Analysis)
# ===================================================================


class HurstExponent(WindowIndicator):
    """Hurst Exponent via Rescaled Range (R/S) analysis.

    Interpretation:
        H < 0.4  — strong mean reversion
        0.4 < H < 0.6 — random walk / inefficient
        H > 0.6  — trending
        H > 0.9  — strong trend (possible bubble)

    Uses multiple sub-window sizes to compute log(R/S) vs log(n).
    """

    def __init__(self, min_window: int = 8, max_window: int = 128) -> None:
        super().__init__(max_window)
        self.min_window = min_window
        self.max_window = max_window
        self.name = f"Hurst({min_window},{max_window})"

    def compute_next_value(self, window: list[float]) -> float:
        prices = np.array(window, dtype=float)
        n = len(prices)

        if n < self.min_window:
            return 0.5  # default to random walk when insufficient data

        # Log returns (guard against non-positive prices)
        if prices.min() <= 0:
            prices = prices - prices.min() + 1.0
        log_returns = np.diff(np.log(prices))

        # Compute R/S over multiple window sizes
        max_lag = min(n // 2, self.max_window)
        lags = range(self.min_window, max_lag)

        if len(lags) < 3:
            return 0.5

        rs_vals = []
        for lag in lags:
            # Split into segments
            n_segments = len(log_returns) // lag
            if n_segments < 1:
                continue

            segments = log_returns[: n_segments * lag].reshape(n_segments, lag)

            # Mean-adjust each segment
            means = segments.mean(axis=1, keepdims=True)
            deviations = segments - means

            # Cumulative sum
            cumulative = deviations.cumsum(axis=1)

            # Range
            r = cumulative.max(axis=1) - cumulative.min(axis=1)

            # Standard deviation
            s = segments.std(axis=1, ddof=1)

            # Avoid division by zero
            valid = s > 0
            if valid.any():
                rs_val = (r[valid] / s[valid]).mean()
                rs_vals.append(rs_val)

        if len(rs_vals) < 3:
            return 0.5

        # Fit log(R/S) = log(c) + H * log(n)
        lags_valid = np.array(list(lags)[: len(rs_vals)])
        log_lags = np.log(lags_valid)
        log_rs = np.log(np.array(rs_vals))

        # Linear regression
        coeffs = P.polyfit(log_lags, log_rs, 1)
        hurst = coeffs[1] / 2.0  # Slope is 2H (for log returns, H = slope/2)

        return round(max(0.0, min(1.0, hurst)), 6)

    def reset(self) -> None:
        super().reset()


# ===================================================================
# ZigZag
# ===================================================================


@dataclass
class ZigZagPoint:
    """A detected swing point."""

    index: int
    price: float
    is_high: bool  # True = peak, False = trough


class ZigZag(WindowIndicator):
    """ZigZag indicator — percentage-threshold swing detection.

    Detects local peaks/troughs by filtering out moves smaller than
    ``deviation_pct``.  Returns the list of swing points in the current window.
    """

    def __init__(self, deviation_pct: float = 5.0, lookback: int = 10) -> None:
        super().__init__(max(lookback * 2, 10))
        self.deviation_pct = deviation_pct / 100.0  # convert to decimal
        self.lookback = lookback
        self.name = f"ZigZag({deviation_pct}%)"

    def compute_next_value(self, window: list[float]) -> list[ZigZagPoint]:
        """Returns list of detected swing points.

        The return type is ``list[ZigZagPoint]``.  Use ``current_value`` to
        access the most recently detected point.
        """
        prices = np.array(window, dtype=float)
        n = len(prices)
        if n < 3:
            return []

        threshold = self.deviation_pct
        points: list[ZigZagPoint] = []
        is_looking_for_high = True  # start looking for a peak

        pivot_idx = 0
        pivot_price = prices[0]
        is_high = True

        for i in range(1, n - 1):
            # Check if i is a local extreme
            if prices[i] > prices[i - 1] and prices[i] >= prices[i + 1]:
                # Local peak
                if is_looking_for_high:
                    if abs(prices[i] - pivot_price) / pivot_price >= threshold:
                        points.append(ZigZagPoint(index=pivot_idx, price=pivot_price, is_high=is_looking_for_high))
                        pivot_idx = i
                        pivot_price = prices[i]
                        is_looking_for_high = False
                elif prices[i] > pivot_price:
                    pivot_idx = i
                    pivot_price = prices[i]
                elif abs(prices[i] - pivot_price) / pivot_price >= threshold:
                    points.append(ZigZagPoint(index=pivot_idx, price=pivot_price, is_high=is_looking_for_high))
                    pivot_idx = i
                    pivot_price = prices[i]
                    is_looking_for_high = True

            elif prices[i] <= prices[i - 1] and prices[i] < prices[i + 1]:
                # Local trough
                if not is_looking_for_high:
                    if abs(prices[i] - pivot_price) / pivot_price >= threshold:
                        points.append(ZigZagPoint(index=pivot_idx, price=pivot_price, is_high=is_looking_for_high))
                        pivot_idx = i
                        pivot_price = prices[i]
                        is_looking_for_high = True
                elif prices[i] < pivot_price:
                    pivot_idx = i
                    pivot_price = prices[i]
                elif abs(prices[i] - pivot_price) / pivot_price >= threshold:
                    points.append(ZigZagPoint(index=pivot_idx, price=pivot_price, is_high=is_looking_for_high))
                    pivot_idx = i
                    pivot_price = prices[i]
                    is_looking_for_high = False

        # Final push
        if len(points) >= 1:
            points.append(ZigZagPoint(index=n - 1, price=prices[-1], is_high=not points[-1].is_high))

        return points

    def reset(self) -> None:
        super().reset()
