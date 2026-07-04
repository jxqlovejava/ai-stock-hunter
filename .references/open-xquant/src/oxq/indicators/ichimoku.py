"""Ichimoku Cloud (一目均衡表) indicators."""

from __future__ import annotations

import pandas as pd


def _midpoint(mktdata: pd.DataFrame, period: int) -> pd.Series:
    """Return (highest high + lowest low) / 2 over a rolling window."""
    high = mktdata["high"].rolling(period).max()
    low = mktdata["low"].rolling(period).min()
    return (high + low) / 2


class IchimokuTenkan:
    """Tenkan-sen (転換線 Conversion Line).

    Tenkan = (highest_high(period) + lowest_low(period)) / 2
    """

    name = "IchimokuTenkan"
    formula = r"Tenkan_t = \frac{HH_{9} + LL_{9}}{2}"

    def compute(
        self, mktdata: pd.DataFrame, period: int = 9,
    ) -> pd.Series:
        """Return Tenkan-sen series (first ``period - 1`` values will be NaN)."""
        return _midpoint(mktdata, period)


class IchimokuKijun:
    """Kijun-sen (基準線 Base Line).

    Kijun = (highest_high(period) + lowest_low(period)) / 2
    """

    name = "IchimokuKijun"
    formula = r"Kijun_t = \frac{HH_{26} + LL_{26}}{2}"

    def compute(
        self, mktdata: pd.DataFrame, period: int = 26,
    ) -> pd.Series:
        """Return Kijun-sen series (first ``period - 1`` values will be NaN)."""
        return _midpoint(mktdata, period)


class IchimokuSenkouA:
    """Senkou Span A (先行スパンA Leading Span A).

    SenkouA = (Tenkan + Kijun) / 2, shifted forward by displacement periods.
    """

    name = "IchimokuSenkouA"
    formula = r"SenkouA_t = \frac{Tenkan_t + Kijun_t}{2}, \text{shifted +displacement}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        tenkan_period: int = 9,
        kijun_period: int = 26,
        displacement: int = 26,
    ) -> pd.Series:
        """Return Senkou Span A shifted forward by ``displacement`` periods."""
        tenkan = _midpoint(mktdata, tenkan_period)
        kijun = _midpoint(mktdata, kijun_period)
        return ((tenkan + kijun) / 2).shift(displacement)


class IchimokuSenkouB:
    """Senkou Span B (先行スパンB Leading Span B).

    SenkouB = (highest_high(period) + lowest_low(period)) / 2, shifted forward.
    """

    name = "IchimokuSenkouB"
    formula = r"SenkouB_t = \frac{HH_{52} + LL_{52}}{2}, \text{shifted +displacement}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        period: int = 52,
        displacement: int = 26,
    ) -> pd.Series:
        """Return Senkou Span B shifted forward by ``displacement`` periods."""
        return _midpoint(mktdata, period).shift(displacement)


class IchimokuChikou:
    """Chikou Span (遅行スパン Lagging Span).

    Chikou = close shifted backward by displacement periods.
    """

    name = "IchimokuChikou"
    formula = r"Chikou_t = Close_{t-displacement}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        column: str = "close",
        displacement: int = 26,
    ) -> pd.Series:
        """Return Chikou Span (close shifted back by ``displacement`` periods)."""
        return mktdata[column].shift(displacement)
