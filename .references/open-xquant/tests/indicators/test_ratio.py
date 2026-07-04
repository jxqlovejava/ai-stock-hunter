"""Tests for Ratio indicator."""

import numpy as np
import pandas as pd

from oxq.core.types import Indicator
from oxq.indicators.ratio import Ratio


def _make_mktdata(col_a_vals: list[float], col_b_vals: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(col_a_vals))
    return pd.DataFrame(
        {"close": col_a_vals, "momentum": col_a_vals, "volatility": col_b_vals},
        index=dates,
    )


def test_ratio_satisfies_indicator_protocol() -> None:
    assert isinstance(Ratio(), Indicator)


def test_ratio_basic() -> None:
    mktdata = _make_mktdata([10.0, 20.0, 30.0], [2.0, 5.0, 10.0])
    result = Ratio().compute(mktdata, col_a="momentum", col_b="volatility")
    assert result.iloc[0] == 5.0
    assert result.iloc[1] == 4.0
    assert result.iloc[2] == 3.0


def test_ratio_with_nan() -> None:
    mktdata = _make_mktdata([float("nan"), 20.0], [2.0, 5.0])
    result = Ratio().compute(mktdata, col_a="momentum", col_b="volatility")
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == 4.0


def test_ratio_division_by_zero() -> None:
    mktdata = _make_mktdata([10.0, 20.0], [0.0, 5.0])
    result = Ratio().compute(mktdata, col_a="momentum", col_b="volatility")
    assert np.isinf(result.iloc[0]) or np.isnan(result.iloc[0])
    assert result.iloc[1] == 4.0


def test_ratio_has_name() -> None:
    assert Ratio().name == "Ratio"
