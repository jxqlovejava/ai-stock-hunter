"""Tests for RollingMDD indicator."""

import numpy as np
import pandas as pd

from oxq.core.types import Indicator
from oxq.indicators.rolling_mdd import RollingMDD


def _make_mktdata(closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000},
        index=dates,
    )


def test_rolling_mdd_satisfies_indicator_protocol() -> None:
    assert isinstance(RollingMDD(), Indicator)


def test_rolling_mdd_basic() -> None:
    closes = [100.0, 110.0, 105.0, 108.0, 95.0]
    mktdata = _make_mktdata(closes)
    result = RollingMDD().compute(mktdata, period=3)
    assert len(result) == 5
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    non_nan = result.dropna()
    assert all(v <= 0.0 for v in non_nan)


def test_rolling_mdd_monotonic_up_is_zero() -> None:
    mktdata = _make_mktdata([100.0, 110.0, 120.0, 130.0, 140.0])
    result = RollingMDD().compute(mktdata, period=3)
    non_nan = result.dropna()
    assert all(v == 0.0 for v in non_nan)


def test_rolling_mdd_has_name() -> None:
    assert RollingMDD().name == "RollingMDD"
