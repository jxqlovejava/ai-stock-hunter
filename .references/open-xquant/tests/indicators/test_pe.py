"""Tests for PE indicator."""

import numpy as np
import pandas as pd

from oxq.core.types import Indicator
from oxq.indicators.pe import PE


def _make_mktdata(closes, eps_values, bvps_values) -> pd.DataFrame:
    n = len(closes)
    dates = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": 1000,
            "eps": eps_values,
            "book_value_per_share": bvps_values,
            "total_shares": [1_000_000] * n,
        },
        index=dates,
    )


def test_pe_satisfies_indicator_protocol() -> None:
    assert isinstance(PE(), Indicator)


def test_pe_basic() -> None:
    mktdata = _make_mktdata([100.0, 200.0, 50.0], [10.0, 25.0, 5.0], [1.0, 1.0, 1.0])
    result = PE().compute(mktdata)
    assert result.iloc[0] == 10.0
    assert result.iloc[1] == 8.0
    assert result.iloc[2] == 10.0


def test_pe_hand_calculated() -> None:
    # price=150, eps=12 -> PE=12.5
    # price=80, eps=4 -> PE=20.0
    mktdata = _make_mktdata([150.0, 80.0], [12.0, 4.0], [1.0, 1.0])
    result = PE().compute(mktdata)
    assert result.iloc[0] == 12.5
    assert result.iloc[1] == 20.0


def test_pe_constant_price() -> None:
    # When EPS is 0 or NaN, PE should be NaN
    mktdata = _make_mktdata([100.0, 100.0, 100.0], [0.0, float("nan"), 5.0], [1.0, 1.0, 1.0])
    result = PE().compute(mktdata)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == 20.0


def test_pe_has_name() -> None:
    assert PE().name == "PE"
