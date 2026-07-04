"""Tests for PB indicator."""

import numpy as np
import pandas as pd

from oxq.core.types import Indicator
from oxq.indicators.pb import PB


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


def test_pb_satisfies_indicator_protocol() -> None:
    assert isinstance(PB(), Indicator)


def test_pb_basic() -> None:
    mktdata = _make_mktdata([100.0, 200.0, 50.0], [1.0, 1.0, 1.0], [50.0, 100.0, 25.0])
    result = PB().compute(mktdata)
    assert result.iloc[0] == 2.0
    assert result.iloc[1] == 2.0
    assert result.iloc[2] == 2.0


def test_pb_hand_calculated() -> None:
    # price=150, bvps=60 -> PB=2.5
    # price=80, bvps=32 -> PB=2.5
    mktdata = _make_mktdata([150.0, 80.0], [1.0, 1.0], [60.0, 32.0])
    result = PB().compute(mktdata)
    assert result.iloc[0] == 2.5
    assert result.iloc[1] == 2.5


def test_pb_constant_price() -> None:
    # When BVPS is 0 or NaN, PB should be NaN
    mktdata = _make_mktdata([100.0, 100.0, 100.0], [1.0, 1.0, 1.0], [0.0, float("nan"), 25.0])
    result = PB().compute(mktdata)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == 4.0


def test_pb_has_name() -> None:
    assert PB().name == "PB"
