"""Tests for ROEChange indicator."""

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.roe_change import ROEChange


def _make_mktdata(closes, roe_values):
    n = len(closes)
    dates = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": 1000,
            "roe": roe_values,
        },
        index=dates,
    )


def test_roe_change_satisfies_indicator_protocol() -> None:
    assert isinstance(ROEChange(), Indicator)


def test_roe_change_basic() -> None:
    mktdata = _make_mktdata(
        [100.0, 100.0, 100.0, 100.0],
        [0.10, 0.12, 0.08, 0.15],
    )
    result = ROEChange().compute(mktdata)
    assert np.isnan(result.iloc[0])
    # 0.12-0.10=0.02, 0.08-0.12=-0.04, 0.15-0.08=0.07
    assert result.iloc[1] == pytest.approx(0.02)
    assert result.iloc[2] == pytest.approx(-0.04)
    assert result.iloc[3] == pytest.approx(0.07)


def test_roe_change_hand_calculated() -> None:
    mktdata = _make_mktdata(
        [100.0, 100.0, 100.0, 100.0, 100.0],
        [0.20, 0.25, 0.18, 0.30, 0.22],
    )
    result = ROEChange().compute(mktdata, period=2)
    # First 2 values NaN
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    # 0.18-0.20=-0.02, 0.30-0.25=0.05, 0.22-0.18=0.04
    assert result.iloc[2] == pytest.approx(-0.02)
    assert result.iloc[3] == pytest.approx(0.05)
    assert result.iloc[4] == pytest.approx(0.04)


def test_roe_change_constant_price() -> None:
    """When ROE is constant, change should be 0 (except first NaN)."""
    mktdata = _make_mktdata(
        [100.0, 100.0, 100.0, 100.0],
        [0.15, 0.15, 0.15, 0.15],
    )
    result = ROEChange().compute(mktdata)
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == pytest.approx(0.0)
    assert result.iloc[2] == pytest.approx(0.0)
    assert result.iloc[3] == pytest.approx(0.0)


def test_roe_change_has_name() -> None:
    assert ROEChange().name == "ROEChange"
