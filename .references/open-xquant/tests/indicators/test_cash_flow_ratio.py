"""Tests for CashFlowRatio indicator."""

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.cash_flow_ratio import CashFlowRatio


def _make_mktdata(closes, ocf, total_assets):
    n = len(closes)
    dates = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": 1000,
            "operating_cash_flow": ocf,
            "total_assets": total_assets,
        },
        index=dates,
    )


def test_cash_flow_ratio_satisfies_indicator_protocol() -> None:
    assert isinstance(CashFlowRatio(), Indicator)


def test_cash_flow_ratio_basic() -> None:
    mktdata = _make_mktdata(
        [100.0, 100.0, 100.0],
        [50.0, 80.0, 30.0],
        [200.0, 400.0, 100.0],
    )
    result = CashFlowRatio().compute(mktdata)
    # 50/200=0.25, 80/400=0.2, 30/100=0.3
    assert result.iloc[0] == pytest.approx(0.25)
    assert result.iloc[1] == pytest.approx(0.2)
    assert result.iloc[2] == pytest.approx(0.3)


def test_cash_flow_ratio_hand_calculated() -> None:
    mktdata = _make_mktdata(
        [100.0, 100.0],
        [75.0, 150.0],
        [500.0, 300.0],
    )
    result = CashFlowRatio().compute(mktdata)
    # 75/500=0.15, 150/300=0.5
    assert result.iloc[0] == pytest.approx(0.15)
    assert result.iloc[1] == pytest.approx(0.5)


def test_cash_flow_ratio_constant_price() -> None:
    """When total_assets is 0 or NaN, result should be NaN."""
    mktdata = _make_mktdata(
        [100.0, 100.0, 100.0],
        [50.0, 50.0, 50.0],
        [0.0, float("nan"), 200.0],
    )
    result = CashFlowRatio().compute(mktdata)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(0.25)


def test_cash_flow_ratio_has_name() -> None:
    assert CashFlowRatio().name == "CashFlowRatio"
