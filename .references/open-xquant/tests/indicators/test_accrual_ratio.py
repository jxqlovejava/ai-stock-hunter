"""Tests for AccrualRatio indicator."""

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.accrual_ratio import AccrualRatio


def _make_mktdata(closes, net_income, ocf, total_assets):
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
            "operating_cash_flow": ocf,
            "total_assets": total_assets,
        },
        index=dates,
    )


def test_accrual_ratio_satisfies_indicator_protocol() -> None:
    assert isinstance(AccrualRatio(), Indicator)


def test_accrual_ratio_basic() -> None:
    mktdata = _make_mktdata(
        [100.0, 100.0, 100.0],
        [50.0, 80.0, 30.0],
        [30.0, 60.0, 40.0],
        [200.0, 400.0, 100.0],
    )
    result = AccrualRatio().compute(mktdata)
    # (50-30)/200=0.1, (80-60)/400=0.05, (30-40)/100=-0.1
    assert result.iloc[0] == pytest.approx(0.1)
    assert result.iloc[1] == pytest.approx(0.05)
    assert result.iloc[2] == pytest.approx(-0.1)


def test_accrual_ratio_hand_calculated() -> None:
    mktdata = _make_mktdata(
        [100.0, 100.0],
        [120.0, 90.0],
        [100.0, 100.0],
        [500.0, 250.0],
    )
    result = AccrualRatio().compute(mktdata)
    # (120-100)/500 = 0.04, (90-100)/250 = -0.04
    assert result.iloc[0] == pytest.approx(0.04)
    assert result.iloc[1] == pytest.approx(-0.04)


def test_accrual_ratio_constant_price() -> None:
    """When total_assets is 0 or NaN, result should be NaN."""
    mktdata = _make_mktdata(
        [100.0, 100.0, 100.0],
        [50.0, 50.0, 50.0],
        [30.0, 30.0, 30.0],
        [0.0, float("nan"), 200.0],
    )
    result = AccrualRatio().compute(mktdata)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(0.1)


def test_accrual_ratio_has_name() -> None:
    assert AccrualRatio().name == "AccrualRatio"
