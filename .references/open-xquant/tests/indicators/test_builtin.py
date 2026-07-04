"""Tests for the 20 built-in technical indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.builtin import (
    ADX,
    AROON,
    ATR,
    CCI,
    DEMA,
    EMA,
    MFI,
    OBV,
    PPO,
    ROC,
    RSI,
    TEMA,
    VWAP,
    WMA,
    BollingerLower,
    BollingerUpper,
    MACDHistogram,
    MACDLine,
    MACDSignal,
    StochK,
)
from oxq.indicators.log_return import LogReturn
from oxq.indicators.momentum import Momentum
from oxq.indicators.nday_return import NdayReturn
from oxq.indicators.ratio import Ratio
from oxq.indicators.rolling_mdd import RollingMDD
from oxq.indicators.rolling_volatility import RollingVolatility
from oxq.indicators.sma import SMA
from oxq.core.registry import list_indicators

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_mktdata(closes: list[float]) -> pd.DataFrame:
    """Minimal mktdata from close prices (H=L=O=C, volume=1000)."""
    dates = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000},
        index=dates,
    )


def _make_ohlcv(n: int = 30) -> pd.DataFrame:
    """Synthetic OHLCV with deterministic random seed."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = 100.0 + rng.standard_normal(n).cumsum()
    high = close + rng.uniform(0, 2, n)
    low = close - rng.uniform(0, 2, n)
    volume = rng.integers(1000, 5000, n).astype(float)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


# ═══════════════════════════════════════════════════════════════════════════
# EMA
# ═══════════════════════════════════════════════════════════════════════════


class TestEMA:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(EMA(), Indicator)

    def test_has_name(self) -> None:
        assert EMA().name == "EMA"

    def test_basic(self) -> None:
        # EMA with period=3 → alpha = 2/(3+1) = 0.5
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = EMA().compute(mktdata, period=3)
        # EMA₀=10, EMA₁=0.5*20+0.5*10=15, EMA₂=0.5*30+0.5*15=22.5
        assert result.iloc[0] == pytest.approx(10.0)
        assert result.iloc[1] == pytest.approx(15.0)
        assert result.iloc[2] == pytest.approx(22.5)

    def test_no_nan(self) -> None:
        """EMA has no NaN lead-in (unlike rolling-based indicators)."""
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = EMA().compute(mktdata, period=3)
        assert not result.isna().any()


# ═══════════════════════════════════════════════════════════════════════════
# WMA
# ═══════════════════════════════════════════════════════════════════════════


class TestWMA:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(WMA(), Indicator)

    def test_has_name(self) -> None:
        assert WMA().name == "WMA"

    def test_basic(self) -> None:
        # WMA [10, 20, 30] period=3: (1*10 + 2*20 + 3*30) / 6 = 140/6 ≈ 23.33
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = WMA().compute(mktdata, period=3)
        assert result.iloc[2] == pytest.approx(140.0 / 6.0)

    def test_nan_leadin(self) -> None:
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = WMA().compute(mktdata, period=3)
        assert np.isnan(result.iloc[0])
        assert np.isnan(result.iloc[1])


# ═══════════════════════════════════════════════════════════════════════════
# DEMA
# ═══════════════════════════════════════════════════════════════════════════


class TestDEMA:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(DEMA(), Indicator)

    def test_has_name(self) -> None:
        assert DEMA().name == "DEMA"

    def test_basic(self) -> None:
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = DEMA().compute(mktdata, period=3)
        # α=0.5; ema1=[10, 15, 22.5]; ema2=[10, 12.5, 17.5]
        # DEMA = 2*ema1 - ema2 = [10, 17.5, 27.5]
        assert result.iloc[0] == pytest.approx(10.0)
        assert result.iloc[1] == pytest.approx(17.5)
        assert result.iloc[2] == pytest.approx(27.5)

    def test_no_nan(self) -> None:
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = DEMA().compute(mktdata, period=3)
        assert not result.isna().any()


# ═══════════════════════════════════════════════════════════════════════════
# TEMA
# ═══════════════════════════════════════════════════════════════════════════


class TestTEMA:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(TEMA(), Indicator)

    def test_has_name(self) -> None:
        assert TEMA().name == "TEMA"

    def test_basic(self) -> None:
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = TEMA().compute(mktdata, period=3)
        # α=0.5; ema1=[10,15,22.5]; ema2=[10,12.5,17.5]; ema3=[10,11.25,14.375]
        # TEMA = 3*ema1 - 3*ema2 + ema3 = [10, 18.75, 29.375]
        assert result.iloc[0] == pytest.approx(10.0)
        assert result.iloc[1] == pytest.approx(18.75)
        assert result.iloc[2] == pytest.approx(29.375)

    def test_no_nan(self) -> None:
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = TEMA().compute(mktdata, period=3)
        assert not result.isna().any()


# ═══════════════════════════════════════════════════════════════════════════
# RSI
# ═══════════════════════════════════════════════════════════════════════════


class TestRSI:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(RSI(), Indicator)

    def test_has_name(self) -> None:
        assert RSI().name == "RSI"

    def test_nan_leadin(self) -> None:
        mktdata = _make_ohlcv(30)
        result = RSI().compute(mktdata, period=14)
        assert result.iloc[:14].isna().all()
        assert not np.isnan(result.iloc[14])

    def test_all_up_near_100(self) -> None:
        # Monotonically increasing → RSI should be very close to 100
        closes = [100.0 + i * 2.0 for i in range(30)]
        mktdata = _make_mktdata(closes)
        result = RSI().compute(mktdata, period=14)
        assert result.iloc[-1] == pytest.approx(100.0, abs=0.5)

    def test_all_down_near_0(self) -> None:
        closes = [200.0 - i * 2.0 for i in range(30)]
        mktdata = _make_mktdata(closes)
        result = RSI().compute(mktdata, period=14)
        assert result.iloc[-1] == pytest.approx(0.0, abs=0.5)

    def test_range_0_to_100(self) -> None:
        mktdata = _make_ohlcv(50)
        result = RSI().compute(mktdata, period=14)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()


# ═══════════════════════════════════════════════════════════════════════════
# MACDLine
# ═══════════════════════════════════════════════════════════════════════════


class TestMACDLine:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(MACDLine(), Indicator)

    def test_has_name(self) -> None:
        assert MACDLine().name == "MACDLine"

    def test_basic(self) -> None:
        mktdata = _make_ohlcv(50)
        result = MACDLine().compute(mktdata, fast_period=12, slow_period=26)
        assert len(result) == 50
        # MACD = EMA_fast - EMA_slow
        ema_fast = mktdata["close"].ewm(span=12, adjust=False).mean()
        ema_slow = mktdata["close"].ewm(span=26, adjust=False).mean()
        expected = ema_fast - ema_slow
        pd.testing.assert_series_equal(result, expected)

    def test_no_nan(self) -> None:
        mktdata = _make_ohlcv(50)
        result = MACDLine().compute(mktdata)
        assert not result.isna().any()


# ═══════════════════════════════════════════════════════════════════════════
# MACDSignal
# ═══════════════════════════════════════════════════════════════════════════


class TestMACDSignal:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(MACDSignal(), Indicator)

    def test_has_name(self) -> None:
        assert MACDSignal().name == "MACDSignal"

    def test_depends_on(self) -> None:
        assert MACDSignal.depends_on == ("macd",)

    def test_basic(self) -> None:
        mktdata = _make_ohlcv(50)
        macd_line = MACDLine().compute(mktdata)
        mktdata["macd"] = macd_line
        result = MACDSignal().compute(mktdata, macd_col="macd", signal_period=9)
        expected = macd_line.ewm(span=9, adjust=False).mean()
        pd.testing.assert_series_equal(result, expected, check_names=False)


# ═══════════════════════════════════════════════════════════════════════════
# MACDHistogram
# ═══════════════════════════════════════════════════════════════════════════


class TestMACDHistogram:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(MACDHistogram(), Indicator)

    def test_has_name(self) -> None:
        assert MACDHistogram().name == "MACDHistogram"

    def test_depends_on(self) -> None:
        assert MACDHistogram.depends_on == ("macd", "macd_signal")

    def test_basic(self) -> None:
        mktdata = _make_ohlcv(50)
        mktdata["macd"] = MACDLine().compute(mktdata)
        mktdata["macd_signal"] = MACDSignal().compute(mktdata)
        result = MACDHistogram().compute(mktdata)
        expected = mktdata["macd"] - mktdata["macd_signal"]
        pd.testing.assert_series_equal(result, expected)

    def test_macd_dependency_chain(self) -> None:
        """Full MACD chain: MACDLine → MACDSignal → MACDHistogram."""
        mktdata = _make_ohlcv(50)
        mktdata["macd"] = MACDLine().compute(mktdata)
        mktdata["macd_signal"] = MACDSignal().compute(mktdata, macd_col="macd")
        mktdata["macd_hist"] = MACDHistogram().compute(
            mktdata, macd_col="macd", signal_col="macd_signal",
        )
        # Histogram = macd - signal at every point
        pd.testing.assert_series_equal(
            mktdata["macd_hist"],
            mktdata["macd"] - mktdata["macd_signal"],
            check_names=False,
        )


# ═══════════════════════════════════════════════════════════════════════════
# ROC
# ═══════════════════════════════════════════════════════════════════════════


class TestROC:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(ROC(), Indicator)

    def test_has_name(self) -> None:
        assert ROC().name == "ROC"

    def test_basic(self) -> None:
        mktdata = _make_mktdata([100.0, 110.0])
        result = ROC().compute(mktdata, period=1)
        assert result.iloc[1] == pytest.approx(10.0)

    def test_nan_leadin(self) -> None:
        mktdata = _make_mktdata([100.0, 110.0, 120.0])
        result = ROC().compute(mktdata, period=2)
        assert np.isnan(result.iloc[0])
        assert np.isnan(result.iloc[1])
        assert not np.isnan(result.iloc[2])


# ═══════════════════════════════════════════════════════════════════════════
# PPO
# ═══════════════════════════════════════════════════════════════════════════


class TestPPO:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(PPO(), Indicator)

    def test_has_name(self) -> None:
        assert PPO().name == "PPO"

    def test_basic(self) -> None:
        mktdata = _make_ohlcv(50)
        result = PPO().compute(mktdata, fast_period=12, slow_period=26)
        ema_fast = mktdata["close"].ewm(span=12, adjust=False).mean()
        ema_slow = mktdata["close"].ewm(span=26, adjust=False).mean()
        expected = (ema_fast - ema_slow) / ema_slow * 100.0
        pd.testing.assert_series_equal(result, expected)

    def test_no_nan(self) -> None:
        mktdata = _make_ohlcv(50)
        result = PPO().compute(mktdata)
        assert not result.isna().any()


# ═══════════════════════════════════════════════════════════════════════════
# CCI
# ═══════════════════════════════════════════════════════════════════════════


class TestCCI:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(CCI(), Indicator)

    def test_has_name(self) -> None:
        assert CCI().name == "CCI"

    def test_nan_leadin(self) -> None:
        mktdata = _make_ohlcv(30)
        result = CCI().compute(mktdata, period=20)
        assert result.iloc[:19].isna().all()
        assert not np.isnan(result.iloc[19])

    def test_constant_price_zero(self) -> None:
        """Constant price → TP = const → CCI = 0/0 → NaN (by design)."""
        mktdata = _make_mktdata([100.0] * 25)
        result = CCI().compute(mktdata, period=20)
        # When MAD=0 and deviation=0, result is NaN (0/0)
        assert np.isnan(result.iloc[19])


# ═══════════════════════════════════════════════════════════════════════════
# BollingerUpper / BollingerLower
# ═══════════════════════════════════════════════════════════════════════════


class TestBollingerUpper:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(BollingerUpper(), Indicator)

    def test_has_name(self) -> None:
        assert BollingerUpper().name == "BollingerUpper"

    def test_basic(self) -> None:
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = BollingerUpper().compute(mktdata, period=3, offset=2.0)
        sma = pd.Series([10.0, 20.0, 30.0]).rolling(3).mean()
        std = pd.Series([10.0, 20.0, 30.0]).rolling(3).std(ddof=0)
        expected = sma.iloc[2] + 2.0 * std.iloc[2]
        assert result.iloc[2] == pytest.approx(expected)

    def test_nan_leadin(self) -> None:
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = BollingerUpper().compute(mktdata, period=3)
        assert np.isnan(result.iloc[0])
        assert np.isnan(result.iloc[1])


class TestBollingerLower:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(BollingerLower(), Indicator)

    def test_has_name(self) -> None:
        assert BollingerLower().name == "BollingerLower"

    def test_basic(self) -> None:
        mktdata = _make_mktdata([10.0, 20.0, 30.0])
        result = BollingerLower().compute(mktdata, period=3, offset=2.0)
        sma = pd.Series([10.0, 20.0, 30.0]).rolling(3).mean()
        std = pd.Series([10.0, 20.0, 30.0]).rolling(3).std(ddof=0)
        expected = sma.iloc[2] - 2.0 * std.iloc[2]
        assert result.iloc[2] == pytest.approx(expected)

    def test_symmetry(self) -> None:
        """Upper and Lower should be symmetric around SMA."""
        mktdata = _make_mktdata([10.0, 20.0, 30.0, 25.0, 15.0])
        upper = BollingerUpper().compute(mktdata, period=3, offset=2.0)
        lower = BollingerLower().compute(mktdata, period=3, offset=2.0)
        mid = (upper + lower) / 2
        sma = mktdata["close"].rolling(3).mean()
        pd.testing.assert_series_equal(mid, sma)


# ═══════════════════════════════════════════════════════════════════════════
# ATR
# ═══════════════════════════════════════════════════════════════════════════


class TestATR:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(ATR(), Indicator)

    def test_has_name(self) -> None:
        assert ATR().name == "ATR"

    def test_constant_bars(self) -> None:
        """When H=L=C and constant, TR=0 → ATR=0."""
        mktdata = _make_mktdata([100.0] * 20)
        result = ATR().compute(mktdata, period=14)
        valid = result.dropna()
        assert (valid == 0.0).all()

    def test_positive(self) -> None:
        mktdata = _make_ohlcv(30)
        result = ATR().compute(mktdata, period=14)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_nan_leadin(self) -> None:
        mktdata = _make_ohlcv(30)
        result = ATR().compute(mktdata, period=14)
        # min_periods=14 → first 13 values NaN (indices 0-12), index 13 is valid
        assert result.iloc[:13].isna().all()
        assert not np.isnan(result.iloc[13])


# ═══════════════════════════════════════════════════════════════════════════
# OBV
# ═══════════════════════════════════════════════════════════════════════════


class TestOBV:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(OBV(), Indicator)

    def test_has_name(self) -> None:
        assert OBV().name == "OBV"

    def test_basic(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=3)
        mktdata = pd.DataFrame(
            {
                "open": [100.0, 110.0, 105.0],
                "high": [100.0, 110.0, 105.0],
                "low": [100.0, 110.0, 105.0],
                "close": [100.0, 110.0, 105.0],
                "volume": [1000.0, 2000.0, 1500.0],
            },
            index=dates,
        )
        result = OBV().compute(mktdata)
        # bar0: direction=0 → 0
        # bar1: 110>100 → +2000 → 2000
        # bar2: 105<110 → -1500 → 500
        assert result.iloc[0] == pytest.approx(0.0)
        assert result.iloc[1] == pytest.approx(2000.0)
        assert result.iloc[2] == pytest.approx(500.0)

    def test_no_nan(self) -> None:
        mktdata = _make_ohlcv(20)
        result = OBV().compute(mktdata)
        assert not result.isna().any()


# ═══════════════════════════════════════════════════════════════════════════
# VWAP
# ═══════════════════════════════════════════════════════════════════════════


class TestVWAP:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(VWAP(), Indicator)

    def test_has_name(self) -> None:
        assert VWAP().name == "VWAP"

    def test_nan_leadin(self) -> None:
        mktdata = _make_ohlcv(30)
        result = VWAP().compute(mktdata, period=20)
        assert result.iloc[:19].isna().all()
        assert not np.isnan(result.iloc[19])

    def test_uniform_volume(self) -> None:
        """With uniform volume, VWAP = rolling mean of TP."""
        closes = [100.0 + i for i in range(25)]
        dates = pd.bdate_range("2024-01-01", periods=25)
        mktdata = pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000.0},
            index=dates,
        )
        tp = (mktdata["high"] + mktdata["low"] + mktdata["close"]) / 3.0
        result = VWAP().compute(mktdata, period=5)
        expected = tp.rolling(5).mean()
        pd.testing.assert_series_equal(result, expected)


# ═══════════════════════════════════════════════════════════════════════════
# MFI
# ═══════════════════════════════════════════════════════════════════════════


class TestMFI:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(MFI(), Indicator)

    def test_has_name(self) -> None:
        assert MFI().name == "MFI"

    def test_nan_leadin(self) -> None:
        mktdata = _make_ohlcv(30)
        result = MFI().compute(mktdata, period=14)
        assert result.iloc[:14].isna().all()

    def test_range_0_to_100(self) -> None:
        mktdata = _make_ohlcv(50)
        result = MFI().compute(mktdata, period=14)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()


# ═══════════════════════════════════════════════════════════════════════════
# ADX
# ═══════════════════════════════════════════════════════════════════════════


class TestADX:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(ADX(), Indicator)

    def test_has_name(self) -> None:
        assert ADX().name == "ADX"

    def test_nan_leadin(self) -> None:
        mktdata = _make_ohlcv(50)
        result = ADX().compute(mktdata, period=14)
        assert result.iloc[:14].isna().all()

    def test_positive(self) -> None:
        mktdata = _make_ohlcv(50)
        result = ADX().compute(mktdata, period=14)
        valid = result.dropna()
        assert (valid >= 0).all()


# ═══════════════════════════════════════════════════════════════════════════
# AROON
# ═══════════════════════════════════════════════════════════════════════════


class TestAROON:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(AROON(), Indicator)

    def test_has_name(self) -> None:
        assert AROON().name == "AROON"

    def test_monotonic_up(self) -> None:
        """Monotonically increasing → Aroon Up = 100, Aroon Down low → oscillator ≈ 100."""
        closes = [100.0 + i * 2.0 for i in range(30)]
        dates = pd.bdate_range("2024-01-01", periods=30)
        mktdata = pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000},
            index=dates,
        )
        result = AROON().compute(mktdata, period=25)
        # Last bar: highest high is most recent → aroon_up=100
        # Lowest low is oldest → aroon_down=0 → oscillator=100
        assert result.iloc[-1] == pytest.approx(100.0)

    def test_nan_leadin(self) -> None:
        mktdata = _make_ohlcv(30)
        result = AROON().compute(mktdata, period=25)
        assert result.iloc[:25].isna().all()


# ═══════════════════════════════════════════════════════════════════════════
# StochK
# ═══════════════════════════════════════════════════════════════════════════


class TestStochK:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(StochK(), Indicator)

    def test_has_name(self) -> None:
        assert StochK().name == "StochK"

    def test_monotonic_up_100(self) -> None:
        """Monotonically increasing → close = highest_high → %K = 100."""
        closes = [100.0 + i for i in range(20)]
        dates = pd.bdate_range("2024-01-01", periods=20)
        mktdata = pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000},
            index=dates,
        )
        result = StochK().compute(mktdata, period=14)
        assert result.iloc[-1] == pytest.approx(100.0)

    def test_nan_leadin(self) -> None:
        mktdata = _make_ohlcv(20)
        result = StochK().compute(mktdata, period=14)
        assert result.iloc[:13].isna().all()

    def test_range_0_to_100(self) -> None:
        mktdata = _make_ohlcv(50)
        result = StochK().compute(mktdata, period=14)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()


# ═══════════════════════════════════════════════════════════════════════════
# Formula attribute — all indicators
# ═══════════════════════════════════════════════════════════════════════════


ALL_INDICATOR_CLASSES = [
    ADX, AROON, ATR, BollingerLower, BollingerUpper, CCI, DEMA, EMA,
    LogReturn, MACDHistogram, MACDLine, MACDSignal, MFI, Momentum,
    NdayReturn, OBV, PPO, ROC, RSI, Ratio, RollingMDD, RollingVolatility,
    SMA, StochK, TEMA, VWAP, WMA,
]


@pytest.mark.parametrize("cls", ALL_INDICATOR_CLASSES, ids=lambda c: c.name)
def test_indicator_has_formula(cls: type) -> None:
    """Every indicator must have a non-empty formula class attribute."""
    assert hasattr(cls, "formula"), f"{cls.name} missing 'formula'"
    assert isinstance(cls.formula, str)
    assert len(cls.formula) > 0, f"{cls.name} has empty formula"


def test_indicator_types_count() -> None:
    """The indicator registry should contain at least 47 built-in indicators."""
    # >= rather than == because plan 027 makes the registry mutable at runtime;
    # other tests in the same process may have registered mocks before this runs.
    assert len(list_indicators()) >= 47


@pytest.mark.parametrize("name,cls", sorted(list_indicators().items()), ids=lambda x: x if isinstance(x, str) else x.name)
def test_registry_indicator_has_formula(name: str, cls: type) -> None:
    """Every registered indicator must have a non-empty formula."""
    assert hasattr(cls, "formula"), f"{name} missing 'formula'"
    assert len(cls.formula) > 0, f"{name} has empty formula"
