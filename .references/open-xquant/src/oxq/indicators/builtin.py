"""Built-in technical indicators — 20 classic TA indicators.

Covers six categories:
- **Trend:** EMA, WMA, DEMA, TEMA
- **Momentum:** RSI, MACDLine, MACDSignal, MACDHistogram, ROC, PPO, CCI
- **Volatility:** BollingerUpper, BollingerLower, ATR
- **Volume:** OBV, VWAP, MFI
- **Trend Strength:** ADX, AROON
- **Stochastic:** StochK

Multi-output indicators (e.g. MACD) are split into independent classes.
Dependent classes declare a ``depends_on`` class attribute listing the
mktdata column names they read.  The engine logs a warning when a
dependency column is missing — see ``engine.py`` Phase 1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ── Trend ─────────────────────────────────────────────────────────────────


class EMA:
    """Exponential Moving Average."""

    name = "EMA"
    formula = r"EMA_t = \alpha \cdot P_t + (1 - \alpha) \cdot EMA_{t-1}, \quad \alpha = \frac{2}{N+1}"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close", period: int = 20,
    ) -> pd.Series:
        """Return EMA series."""
        return mktdata[column].ewm(span=period, adjust=False).mean()


class WMA:
    """Weighted Moving Average (linearly weighted)."""

    name = "WMA"
    formula = r"WMA_t = \frac{\sum_{i=0}^{N-1} (N-i) \cdot P_{t-i}}{\sum_{i=1}^{N} i}"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close", period: int = 20,
    ) -> pd.Series:
        """Return WMA series (first ``period - 1`` values will be NaN)."""
        weights = np.arange(1, period + 1, dtype=float)
        return mktdata[column].rolling(period).apply(
            lambda x: np.dot(x, weights) / weights.sum(), raw=True,
        )


class DEMA:
    """Double Exponential Moving Average."""

    name = "DEMA"
    formula = r"DEMA_t = 2 \cdot EMA_t - EMA(EMA_t)"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close", period: int = 20,
    ) -> pd.Series:
        """Return DEMA = 2 * EMA - EMA(EMA)."""
        ema1 = mktdata[column].ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        return 2 * ema1 - ema2


class TEMA:
    """Triple Exponential Moving Average."""

    name = "TEMA"
    formula = r"TEMA_t = 3 \cdot EMA_t - 3 \cdot EMA_2_t + EMA_3_t"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close", period: int = 20,
    ) -> pd.Series:
        """Return TEMA = 3*EMA - 3*EMA2 + EMA3."""
        ema1 = mktdata[column].ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        ema3 = ema2.ewm(span=period, adjust=False).mean()
        return 3 * ema1 - 3 * ema2 + ema3


# ── Momentum ──────────────────────────────────────────────────────────────


class RSI:
    """Relative Strength Index (Wilder smoothing)."""

    name = "RSI"
    formula = r"RSI = 100 - \frac{100}{1 + \frac{AvgGain}{AvgLoss}}"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close", period: int = 14,
    ) -> pd.Series:
        """Return RSI in [0, 100]. Uses Wilder's smoothing (ewm alpha=1/period)."""
        delta = mktdata[column].diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1.0 + rs)
        # First (period) values are unreliable — set to NaN
        rsi.iloc[:period] = np.nan
        return rsi


class MACDLine:
    """MACD Line = EMA(fast) - EMA(slow)."""

    name = "MACDLine"
    formula = r"MACD = EMA_{fast} - EMA_{slow}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        column: str = "close",
        fast_period: int = 12,
        slow_period: int = 26,
    ) -> pd.Series:
        """Return MACD line series."""
        ema_fast = mktdata[column].ewm(span=fast_period, adjust=False).mean()
        ema_slow = mktdata[column].ewm(span=slow_period, adjust=False).mean()
        return ema_fast - ema_slow


class MACDSignal:
    """MACD Signal Line = EMA of MACD Line.

    Requires: register MACDLine before this indicator.
    """

    name = "MACDSignal"
    formula = r"Signal = EMA_9(MACD)"
    depends_on = ("macd",)

    def compute(
        self,
        mktdata: pd.DataFrame,
        macd_col: str = "macd",
        signal_period: int = 9,
    ) -> pd.Series:
        """Return MACD signal line (EMA of the MACD column)."""
        return mktdata[macd_col].ewm(span=signal_period, adjust=False).mean()


class MACDHistogram:
    """MACD Histogram = MACD Line - Signal Line.

    Requires: register MACDLine and MACDSignal first.
    """

    name = "MACDHistogram"
    formula = r"Histogram = MACD - Signal"
    depends_on = ("macd", "macd_signal")

    def compute(
        self,
        mktdata: pd.DataFrame,
        macd_col: str = "macd",
        signal_col: str = "macd_signal",
    ) -> pd.Series:
        """Return MACD histogram series."""
        return mktdata[macd_col] - mktdata[signal_col]


class ROC:
    """Rate of Change (percentage)."""

    name = "ROC"
    formula = r"ROC_t = \frac{P_t - P_{t-N}}{P_{t-N}} \times 100"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close", period: int = 10,
    ) -> pd.Series:
        """Return ROC = pct_change(period) * 100."""
        return mktdata[column].pct_change(period) * 100.0


class PPO:
    """Percentage Price Oscillator."""

    name = "PPO"
    formula = r"PPO = \frac{EMA_{fast} - EMA_{slow}}{EMA_{slow}} \times 100"

    def compute(
        self,
        mktdata: pd.DataFrame,
        column: str = "close",
        fast_period: int = 12,
        slow_period: int = 26,
    ) -> pd.Series:
        """Return PPO = (EMA_fast - EMA_slow) / EMA_slow * 100."""
        ema_fast = mktdata[column].ewm(span=fast_period, adjust=False).mean()
        ema_slow = mktdata[column].ewm(span=slow_period, adjust=False).mean()
        return (ema_fast - ema_slow) / ema_slow * 100.0


class CCI:
    """Commodity Channel Index."""

    name = "CCI"
    formula = r"CCI = \frac{TP - SMA(TP)}{0.015 \cdot MAD(TP)}, \quad TP = \frac{H+L+C}{3}"

    def compute(
        self, mktdata: pd.DataFrame, period: int = 20,
    ) -> pd.Series:
        """Return CCI = (TP - SMA(TP)) / (0.015 * MAD(TP)).

        Typical Price = (High + Low + Close) / 3.
        """
        tp = (mktdata["high"] + mktdata["low"] + mktdata["close"]) / 3.0
        sma_tp = tp.rolling(period).mean()
        mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        return (tp - sma_tp) / (0.015 * mad)


# ── Volatility ────────────────────────────────────────────────────────────


class BollingerUpper:
    """Bollinger Band — upper band."""

    name = "BollingerUpper"
    formula = r"Upper = SMA_N + k \cdot \sigma_N"

    def compute(
        self,
        mktdata: pd.DataFrame,
        column: str = "close",
        period: int = 20,
        offset: float = 2.0,
    ) -> pd.Series:
        """Return SMA + offset * rolling std (population)."""
        rolling = mktdata[column].rolling(period)
        return rolling.mean() + offset * rolling.std(ddof=0)


class BollingerLower:
    """Bollinger Band — lower band."""

    name = "BollingerLower"
    formula = r"Lower = SMA_N - k \cdot \sigma_N"

    def compute(
        self,
        mktdata: pd.DataFrame,
        column: str = "close",
        period: int = 20,
        offset: float = 2.0,
    ) -> pd.Series:
        """Return SMA - offset * rolling std (population)."""
        rolling = mktdata[column].rolling(period)
        return rolling.mean() - offset * rolling.std(ddof=0)


class ATR:
    """Average True Range (Wilder smoothing)."""

    name = "ATR"
    formula = r"TR = \max(H-L, |H-C_{prev}|, |L-C_{prev}|), \quad ATR = Wilder(TR, N)"

    def compute(
        self, mktdata: pd.DataFrame, period: int = 14,
    ) -> pd.Series:
        """Return ATR series.

        TR = max(H - L, |H - prev_close|, |L - prev_close|).
        Smoothing uses Wilder's EWM (alpha = 1/period).
        """
        high = mktdata["high"]
        low = mktdata["low"]
        prev_close = mktdata["close"].shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


# ── Volume ────────────────────────────────────────────────────────────────


class OBV:
    """On-Balance Volume."""

    name = "OBV"
    formula = r"OBV_t = OBV_{t-1} + sign(\Delta C_t) \cdot V_t"

    def compute(
        self, mktdata: pd.DataFrame, column: str = "close",
    ) -> pd.Series:
        """Return cumulative OBV.

        +volume when close > prev_close, -volume when close < prev_close,
        0 when unchanged.
        """
        direction = np.sign(mktdata[column].diff())
        # First bar has no previous close — direction is NaN → set to 0
        direction.iloc[0] = 0.0
        return (direction * mktdata["volume"]).cumsum()


class VWAP:
    """Volume-Weighted Average Price (rolling)."""

    name = "VWAP"
    formula = r"VWAP = \frac{\sum_{i} TP_i \cdot V_i}{\sum_{i} V_i}"

    def compute(
        self, mktdata: pd.DataFrame, period: int = 20,
    ) -> pd.Series:
        """Return rolling VWAP = sum(TP * V) / sum(V) over *period* bars."""
        tp = (mktdata["high"] + mktdata["low"] + mktdata["close"]) / 3.0
        tp_vol = tp * mktdata["volume"]
        return tp_vol.rolling(period).sum() / mktdata["volume"].rolling(period).sum()


class MFI:
    """Money Flow Index."""

    name = "MFI"
    formula = r"MFI = 100 - \frac{100}{1 + \frac{PositiveFlow}{NegativeFlow}}"

    def compute(
        self, mktdata: pd.DataFrame, period: int = 14,
    ) -> pd.Series:
        """Return MFI in [0, 100].

        TP = (H + L + C) / 3, raw_money_flow = TP * volume.
        MFI = 100 - 100 / (1 + positive_flow / negative_flow).
        """
        tp = (mktdata["high"] + mktdata["low"] + mktdata["close"]) / 3.0
        raw_mf = tp * mktdata["volume"]
        delta_tp = tp.diff()
        pos_flow = (raw_mf * (delta_tp > 0)).rolling(period).sum()
        neg_flow = (raw_mf * (delta_tp < 0)).rolling(period).sum()
        mfi = 100.0 - 100.0 / (1.0 + pos_flow / neg_flow)
        mfi.iloc[:period] = np.nan
        return mfi


# ── Trend Strength ────────────────────────────────────────────────────────


class ADX:
    """Average Directional Index."""

    name = "ADX"
    formula = r"ADX = Wilder\left(\frac{|+DI - (-DI)|}{+DI + (-DI)} \times 100, N\right)"

    def compute(
        self, mktdata: pd.DataFrame, period: int = 14,
    ) -> pd.Series:
        """Return ADX series.

        +DM / -DM → smoothed +DI / -DI → DX → smoothed ADX.
        """
        high = mktdata["high"]
        low = mktdata["low"]
        prev_close = mktdata["close"].shift(1)

        # True Range
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)

        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        alpha = 1.0 / period
        atr = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        smooth_plus = pd.Series(plus_dm, index=mktdata.index).ewm(
            alpha=alpha, min_periods=period, adjust=False,
        ).mean()
        smooth_minus = pd.Series(minus_dm, index=mktdata.index).ewm(
            alpha=alpha, min_periods=period, adjust=False,
        ).mean()

        plus_di = 100.0 * smooth_plus / atr
        minus_di = 100.0 * smooth_minus / atr
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        adx.iloc[:period] = np.nan
        return adx


class AROON:
    """Aroon Oscillator (Aroon Up - Aroon Down)."""

    name = "AROON"
    formula = r"Aroon = \frac{bars\_since\_high}{N} \times 100 - \frac{bars\_since\_low}{N} \times 100"

    def compute(
        self, mktdata: pd.DataFrame, period: int = 25,
    ) -> pd.Series:
        """Return Aroon oscillator = Aroon Up - Aroon Down.

        Aroon Up   = 100 * (period - bars_since_highest_high) / period
        Aroon Down = 100 * (period - bars_since_lowest_low)   / period
        """
        high_roll = mktdata["high"].rolling(period + 1)
        low_roll = mktdata["low"].rolling(period + 1)
        aroon_up = high_roll.apply(lambda x: x.argmax(), raw=True) / period * 100.0
        aroon_down = low_roll.apply(lambda x: x.argmin(), raw=True) / period * 100.0
        return aroon_up - aroon_down


# ── Stochastic ────────────────────────────────────────────────────────────


class StochK:
    """Stochastic %K."""

    name = "StochK"
    formula = r"\%K = \frac{C - L_N}{H_N - L_N} \times 100"

    def compute(
        self, mktdata: pd.DataFrame, period: int = 14,
    ) -> pd.Series:
        """Return %K = (close - lowest_low) / (highest_high - lowest_low) * 100."""
        lowest = mktdata["low"].rolling(period).min()
        highest = mktdata["high"].rolling(period).max()
        return (mktdata["close"] - lowest) / (highest - lowest) * 100.0
