"""Tests for NdayReturn indicator."""

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.nday_return import NdayReturn


def _make_mktdata(closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000},
        index=dates,
    )


def test_nday_return_satisfies_indicator_protocol() -> None:
    assert isinstance(NdayReturn(), Indicator)


def test_nday_return_basic() -> None:
    mktdata = _make_mktdata([100.0, 110.0, 121.0, 115.0, 130.0])
    result = NdayReturn().compute(mktdata, period=3)
    assert len(result) == 5
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert np.isnan(result.iloc[2])
    assert result.iloc[3] == pytest.approx(np.log(115.0) - np.log(100.0))
    assert result.iloc[4] == pytest.approx(np.log(130.0) - np.log(110.0))


def test_nday_return_period_1_equals_log_return() -> None:
    mktdata = _make_mktdata([100.0, 110.0, 105.0])
    result = NdayReturn().compute(mktdata, period=1)
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == pytest.approx(np.log(110.0) - np.log(100.0))


def test_nday_return_has_name() -> None:
    assert NdayReturn().name == "NdayReturn"
