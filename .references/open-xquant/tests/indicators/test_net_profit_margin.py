"""Tests for NetProfitMargin indicator."""

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.net_profit_margin import NetProfitMargin


def _make_mktdata(closes, net_income, revenue):
    n = len(closes)
    dates = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": 1000,
            "net_income": net_income,
            "revenue": revenue,
        },
        index=dates,
    )


def test_net_profit_margin_satisfies_indicator_protocol() -> None:
    assert isinstance(NetProfitMargin(), Indicator)


def test_net_profit_margin_basic() -> None:
    mktdata = _make_mktdata(
        [100.0, 100.0, 100.0],
        [20.0, 50.0, 10.0],
        [100.0, 200.0, 50.0],
    )
    result = NetProfitMargin().compute(mktdata)
    # 20/100=0.2, 50/200=0.25, 10/50=0.2
    assert result.iloc[0] == pytest.approx(0.2)
    assert result.iloc[1] == pytest.approx(0.25)
    assert result.iloc[2] == pytest.approx(0.2)


def test_net_profit_margin_hand_calculated() -> None:
    mktdata = _make_mktdata(
        [100.0, 100.0],
        [30.0, -15.0],
        [150.0, 300.0],
    )
    result = NetProfitMargin().compute(mktdata)
    # 30/150=0.2, -15/300=-0.05
    assert result.iloc[0] == pytest.approx(0.2)
    assert result.iloc[1] == pytest.approx(-0.05)


def test_net_profit_margin_constant_price() -> None:
    """When revenue is 0 or NaN, result should be NaN."""
    mktdata = _make_mktdata(
        [100.0, 100.0, 100.0],
        [20.0, 20.0, 20.0],
        [0.0, float("nan"), 100.0],
    )
    result = NetProfitMargin().compute(mktdata)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(0.2)


def test_net_profit_margin_has_name() -> None:
    assert NetProfitMargin().name == "NetProfitMargin"
