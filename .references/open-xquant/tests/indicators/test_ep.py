"""Tests for EP indicator."""

import numpy as np
import pandas as pd

from oxq.core.types import Indicator
from oxq.indicators.ep import EP


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


def test_ep_satisfies_indicator_protocol() -> None:
    assert isinstance(EP(), Indicator)


def test_ep_basic() -> None:
    mktdata = _make_mktdata([100.0, 200.0, 50.0], [10.0, 25.0, 5.0], [1.0, 1.0, 1.0])
    result = EP().compute(mktdata)
    assert result.iloc[0] == 0.1
    assert result.iloc[1] == 0.125
    assert result.iloc[2] == 0.1


def test_ep_hand_calculated() -> None:
    # eps=12, price=150 -> EP=0.08
    # eps=4, price=80 -> EP=0.05
    mktdata = _make_mktdata([150.0, 80.0], [12.0, 4.0], [1.0, 1.0])
    result = EP().compute(mktdata)
    assert result.iloc[0] == 0.08
    assert result.iloc[1] == 0.05


def test_ep_constant_price() -> None:
    # When price is 0 or NaN, EP should be NaN
    mktdata = _make_mktdata([0.0, float("nan"), 50.0], [10.0, 10.0, 5.0], [1.0, 1.0, 1.0])
    result = EP().compute(mktdata)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == 0.1


def test_ep_has_name() -> None:
    assert EP().name == "EP"
