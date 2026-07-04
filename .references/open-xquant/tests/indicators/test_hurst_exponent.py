"""Tests for HurstExponent indicator."""

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.hurst_exponent import HurstExponent


def _make_mktdata(closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000},
        index=dates,
    )


def test_hurst_exponent_satisfies_indicator_protocol() -> None:
    assert isinstance(HurstExponent(), Indicator)


def test_hurst_exponent_basic() -> None:
    closes = [100.0, 102.0, 101.0, 104.0, 103.0, 106.0, 105.0, 108.0, 107.0, 110.0]
    mktdata = _make_mktdata(closes)
    result = HurstExponent().compute(mktdata, period=5)
    # Length matches input
    assert len(result) == len(closes)
    # Return type is pd.Series
    assert isinstance(result, pd.Series)
    # First 5 values are NaN (insufficient data for period=5)
    assert result.iloc[:5].isna().all()
    # At least some non-NaN values after period
    assert result.dropna().shape[0] > 0
    # Values should be in reasonable range [0, 1.5]
    non_nan = result.dropna()
    assert (non_nan >= 0).all()
    assert (non_nan <= 1.5).all()


def test_hurst_exponent_hand_calculated() -> None:
    """Verify against hand-calculated R/S for a small window."""
    # Use 5 prices → 4 log returns, period=4
    closes = [100.0, 110.0, 105.0, 115.0, 120.0]
    mktdata = _make_mktdata(closes)
    result = HurstExponent().compute(mktdata, period=4)

    # Hand-calculate for last value (index 4, window = log returns at indices 1-4)
    log_prices = np.log(closes)
    log_rets = np.diff(log_prices)  # 4 values
    window = log_rets  # all 4 returns
    mean = np.mean(window)
    devs = window - mean
    cumulative = np.cumsum(devs)
    r = np.max(cumulative) - np.min(cumulative)
    s = np.std(window, ddof=1)
    expected_h = np.log(r / s) / np.log(4)

    assert result.iloc[4] == pytest.approx(expected_h, rel=1e-6)


def test_hurst_exponent_constant_price() -> None:
    """Constant prices produce zero log returns → H should be 0.5 (degenerate)."""
    mktdata = _make_mktdata([100.0] * 10)
    result = HurstExponent().compute(mktdata, period=5)
    non_nan = result.dropna()
    assert all(v == pytest.approx(0.5) for v in non_nan)


def test_hurst_exponent_has_name() -> None:
    assert HurstExponent().name == "HurstExponent"
