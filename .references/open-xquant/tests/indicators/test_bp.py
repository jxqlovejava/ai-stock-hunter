"""Tests for BP indicator."""

import numpy as np
import pandas as pd

from oxq.core.types import Indicator
from oxq.indicators.bp import BP


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


def test_bp_satisfies_indicator_protocol() -> None:
    assert isinstance(BP(), Indicator)


def test_bp_basic() -> None:
    mktdata = _make_mktdata([100.0, 200.0, 50.0], [1.0, 1.0, 1.0], [50.0, 100.0, 25.0])
    result = BP().compute(mktdata)
    assert result.iloc[0] == 0.5
    assert result.iloc[1] == 0.5
    assert result.iloc[2] == 0.5


def test_bp_hand_calculated() -> None:
    # bvps=60, price=150 -> BP=0.4
    # bvps=32, price=80 -> BP=0.4
    mktdata = _make_mktdata([150.0, 80.0], [1.0, 1.0], [60.0, 32.0])
    result = BP().compute(mktdata)
    assert result.iloc[0] == 0.4
    assert result.iloc[1] == 0.4


def test_bp_constant_price() -> None:
    # When price is 0 or NaN, BP should be NaN
    mktdata = _make_mktdata([0.0, float("nan"), 50.0], [1.0, 1.0, 1.0], [25.0, 25.0, 25.0])
    result = BP().compute(mktdata)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == 0.5


def test_bp_has_name() -> None:
    assert BP().name == "BP"
