"""Tests for LogReturn indicator."""

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.log_return import LogReturn


def _make_mktdata(closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000},
        index=dates,
    )


def test_log_return_satisfies_indicator_protocol() -> None:
    assert isinstance(LogReturn(), Indicator)


def test_log_return_basic() -> None:
    mktdata = _make_mktdata([100.0, 110.0, 105.0])
    result = LogReturn().compute(mktdata)
    assert len(result) == 3
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == pytest.approx(np.log(110.0) - np.log(100.0))
    assert result.iloc[2] == pytest.approx(np.log(105.0) - np.log(110.0))


def test_log_return_custom_column() -> None:
    mktdata = _make_mktdata([100.0, 200.0])
    mktdata["volume"] = [1000, 2000]
    result = LogReturn().compute(mktdata, column="volume")
    assert result.iloc[1] == pytest.approx(np.log(2000) - np.log(1000))


def test_log_return_has_name() -> None:
    assert LogReturn().name == "LogReturn"
