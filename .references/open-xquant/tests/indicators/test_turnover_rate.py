"""Tests for TurnoverRate indicator."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.turnover_rate import TurnoverRate


def _make_mktdata(
    volumes: list[float], total_shares: list[float],
) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(volumes))
    return pd.DataFrame(
        {"volume": volumes, "total_shares": total_shares},
        index=dates,
    )


class TestTurnoverRate:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(TurnoverRate(), Indicator)

    def test_has_name(self) -> None:
        assert TurnoverRate().name == "TurnoverRate"

    def test_basic(self) -> None:
        mktdata = _make_mktdata(
            volumes=[1000.0, 2000.0, 3000.0],
            total_shares=[10000.0, 10000.0, 10000.0],
        )
        result = TurnoverRate().compute(mktdata)
        assert result.iloc[0] == pytest.approx(0.1)
        assert result.iloc[1] == pytest.approx(0.2)
        assert result.iloc[2] == pytest.approx(0.3)

    def test_hand_calculated(self) -> None:
        """Hand-calculated: 500/5000=0.1, 1200/4000=0.3, 800/2000=0.4."""
        mktdata = _make_mktdata(
            volumes=[500.0, 1200.0, 800.0],
            total_shares=[5000.0, 4000.0, 2000.0],
        )
        result = TurnoverRate().compute(mktdata)
        assert result.iloc[0] == pytest.approx(0.1)
        assert result.iloc[1] == pytest.approx(0.3)
        assert result.iloc[2] == pytest.approx(0.4)

    def test_constant_price(self) -> None:
        """Constant volume and shares -> constant turnover."""
        mktdata = _make_mktdata(
            volumes=[1000.0] * 5,
            total_shares=[10000.0] * 5,
        )
        result = TurnoverRate().compute(mktdata)
        assert list(result) == pytest.approx([0.1] * 5)

    def test_zero_shares_produces_nan(self) -> None:
        """total_shares=0 should produce NaN."""
        mktdata = _make_mktdata(
            volumes=[1000.0, 2000.0],
            total_shares=[10000.0, 0.0],
        )
        result = TurnoverRate().compute(mktdata)
        assert result.iloc[0] == pytest.approx(0.1)
        assert math.isnan(result.iloc[1])

    def test_missing_shares_produces_nan(self) -> None:
        """NaN in total_shares should produce NaN."""
        mktdata = _make_mktdata(
            volumes=[1000.0, 2000.0],
            total_shares=[10000.0, float("nan")],
        )
        result = TurnoverRate().compute(mktdata)
        assert result.iloc[0] == pytest.approx(0.1)
        assert math.isnan(result.iloc[1])
