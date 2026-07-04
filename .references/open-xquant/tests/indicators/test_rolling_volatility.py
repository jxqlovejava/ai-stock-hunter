"""Tests for RollingVolatility indicator."""

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.rolling_volatility import RollingVolatility


def _make_mktdata(closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000},
        index=dates,
    )


def test_rolling_volatility_satisfies_indicator_protocol() -> None:
    assert isinstance(RollingVolatility(), Indicator)


def test_rolling_volatility_basic() -> None:
    closes = [100.0, 102.0, 101.0, 104.0, 103.0, 106.0]
    mktdata = _make_mktdata(closes)
    result = RollingVolatility().compute(mktdata, period=3)
    assert len(result) == 6

    log_ret = np.diff(np.log(closes))
    expected = np.std(log_ret[0:3], ddof=1)
    assert result.iloc[3] == pytest.approx(expected, rel=1e-6)


def test_rolling_volatility_constant_price_is_zero() -> None:
    mktdata = _make_mktdata([100.0] * 10)
    result = RollingVolatility().compute(mktdata, period=5)
    non_nan = result.dropna()
    assert all(v == 0.0 for v in non_nan)


def test_rolling_volatility_has_name() -> None:
    assert RollingVolatility().name == "RollingVolatility"
