"""Tests for Ichimoku Cloud indicators."""

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.ichimoku import (
    IchimokuChikou,
    IchimokuKijun,
    IchimokuSenkouA,
    IchimokuSenkouB,
    IchimokuTenkan,
)


def _make_mktdata(
    highs: list[float], lows: list[float], closes: list[float],
) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": 1000,
        },
        index=dates,
    )


def _simple_mktdata() -> pd.DataFrame:
    """10-bar dataset with known highs/lows for hand calculations."""
    highs =  [102, 104, 103, 106, 105, 108, 107, 110, 109, 112]
    lows =   [ 98,  99,  97, 100,  99, 102, 101, 104, 103, 106]
    closes = [100, 102, 101, 104, 103, 106, 105, 108, 107, 110]
    return _make_mktdata(
        [float(h) for h in highs],
        [float(l) for l in lows],
        [float(c) for c in closes],
    )


# --------------- Protocol checks ---------------

@pytest.mark.parametrize("cls", [
    IchimokuTenkan, IchimokuKijun, IchimokuSenkouA, IchimokuSenkouB, IchimokuChikou,
])
def test_satisfies_indicator_protocol(cls):
    assert isinstance(cls(), Indicator)


@pytest.mark.parametrize("cls,expected_name", [
    (IchimokuTenkan, "IchimokuTenkan"),
    (IchimokuKijun, "IchimokuKijun"),
    (IchimokuSenkouA, "IchimokuSenkouA"),
    (IchimokuSenkouB, "IchimokuSenkouB"),
    (IchimokuChikou, "IchimokuChikou"),
])
def test_has_name(cls, expected_name):
    assert cls().name == expected_name


# --------------- Tenkan-sen ---------------

def test_tenkan_basic():
    mktdata = _simple_mktdata()
    result = IchimokuTenkan().compute(mktdata, period=3)
    assert len(result) == 10
    assert isinstance(result, pd.Series)
    # period=3, index=2: HH(102,104,103)=104, LL(98,99,97)=97 -> (104+97)/2=100.5
    assert result.iloc[2] == pytest.approx(100.5)
    # index=3: HH(104,103,106)=106, LL(99,97,100)=97 -> (106+97)/2=101.5
    assert result.iloc[3] == pytest.approx(101.5)


def test_tenkan_first_values_nan():
    mktdata = _simple_mktdata()
    result = IchimokuTenkan().compute(mktdata, period=5)
    assert result.iloc[:4].isna().all()
    assert result.iloc[4:].notna().all()


# --------------- Kijun-sen ---------------

def test_kijun_basic():
    mktdata = _simple_mktdata()
    # Use period=5 for testability
    result = IchimokuKijun().compute(mktdata, period=5)
    assert len(result) == 10
    # index=4: HH(102,104,103,106,105)=106, LL(98,99,97,100,99)=97 -> (106+97)/2=101.5
    assert result.iloc[4] == pytest.approx(101.5)


# --------------- Senkou Span A ---------------

def test_senkou_a_basic():
    mktdata = _simple_mktdata()
    # tenkan_period=3, kijun_period=5, displacement=2
    result = IchimokuSenkouA().compute(
        mktdata, tenkan_period=3, kijun_period=5, displacement=2,
    )
    assert len(result) == 10
    # At index=4: tenkan=101.5, kijun=101.5 -> avg=101.5, but shifted +2 so appears at index=6
    # At index=6 we see the value from index=4
    tenkan_at_4 = 101.5  # verified above
    kijun_at_4 = 101.5   # verified above
    expected = (tenkan_at_4 + kijun_at_4) / 2  # 101.5
    assert result.iloc[6] == pytest.approx(expected)
    # First displacement values should be NaN due to shift
    assert result.iloc[:2].isna().all()


# --------------- Senkou Span B ---------------

def test_senkou_b_basic():
    mktdata = _simple_mktdata()
    # period=5, displacement=2
    result = IchimokuSenkouB().compute(mktdata, period=5, displacement=2)
    assert len(result) == 10
    # midpoint at index=4: (106+97)/2=101.5, shifted +2 -> appears at index=6
    assert result.iloc[6] == pytest.approx(101.5)


# --------------- Chikou Span ---------------

def test_chikou_basic():
    mktdata = _simple_mktdata()
    result = IchimokuChikou().compute(mktdata, column="close", displacement=3)
    assert len(result) == 10
    # shift(3) means index=3 gets value of close at index=0 = 100.0
    assert result.iloc[3] == pytest.approx(100.0)
    assert result.iloc[4] == pytest.approx(102.0)
    # First 3 values should be NaN
    assert result.iloc[:3].isna().all()


# --------------- Constant price edge case ---------------

def test_constant_price_midpoint():
    """Constant highs/lows produce constant midpoint."""
    mktdata = _make_mktdata(
        [105.0] * 10, [95.0] * 10, [100.0] * 10,
    )
    result = IchimokuTenkan().compute(mktdata, period=5)
    non_nan = result.dropna()
    assert (non_nan == 100.0).all()
