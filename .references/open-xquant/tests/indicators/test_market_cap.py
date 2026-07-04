"""Tests for MarketCap indicator."""

from __future__ import annotations

import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.market_cap import MarketCap


def _make_mktdata(
    closes: list[float], total_shares: list[float],
) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {"close": closes, "total_shares": total_shares},
        index=dates,
    )


class TestMarketCap:
    def test_satisfies_indicator_protocol(self) -> None:
        assert isinstance(MarketCap(), Indicator)

    def test_has_name(self) -> None:
        assert MarketCap().name == "MarketCap"

    def test_basic(self) -> None:
        mktdata = _make_mktdata(
            closes=[10.0, 20.0, 30.0],
            total_shares=[1000.0, 1000.0, 1000.0],
        )
        result = MarketCap().compute(mktdata)
        assert result.iloc[0] == pytest.approx(10000.0)
        assert result.iloc[1] == pytest.approx(20000.0)
        assert result.iloc[2] == pytest.approx(30000.0)

    def test_hand_calculated(self) -> None:
        """Hand-calculated: 15.5*2000=31000, 22.0*3000=66000, 8.0*5000=40000."""
        mktdata = _make_mktdata(
            closes=[15.5, 22.0, 8.0],
            total_shares=[2000.0, 3000.0, 5000.0],
        )
        result = MarketCap().compute(mktdata)
        assert result.iloc[0] == pytest.approx(31000.0)
        assert result.iloc[1] == pytest.approx(66000.0)
        assert result.iloc[2] == pytest.approx(40000.0)

    def test_constant_price(self) -> None:
        """Constant price and shares -> constant market cap."""
        mktdata = _make_mktdata(
            closes=[100.0] * 5,
            total_shares=[1000.0] * 5,
        )
        result = MarketCap().compute(mktdata)
        assert list(result) == pytest.approx([100000.0] * 5)

    def test_has_name_attr(self) -> None:
        assert hasattr(MarketCap, "name")
        assert MarketCap.name == "MarketCap"
