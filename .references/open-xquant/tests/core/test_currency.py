"""Tests for currency discipline — Phase 2 of timezone-currency plan."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from oxq.core.engine import Engine
from oxq.core.strategy import Strategy
from oxq.core.types import Order, Portfolio
from oxq.portfolio.optimizers import EqualWeightOptimizer
from oxq.trade.sim_broker import SimBroker
from oxq.universe.static import StaticUniverse


def test_order_carries_currency() -> None:
    """Order should have a currency field defaulting to CNY."""
    order = Order(symbol="AAPL", side="BUY", shares=100)
    assert hasattr(order, "currency")
    assert order.currency == "CNY"

    order_usd = Order(symbol="AAPL", side="BUY", shares=100, currency="USD")
    assert order_usd.currency == "USD"


def test_portfolio_currency() -> None:
    """Portfolio should carry a currency field."""
    port = Portfolio(cash=Decimal("100000"))
    assert hasattr(port, "currency")
    assert port.currency == "CNY"

    port_usd = Portfolio(cash=Decimal("100000"), currency="USD")
    assert port_usd.currency == "USD"


def test_portfolio_currency_from_engine() -> None:
    """Engine should set portfolio currency from mktdata attrs."""
    dates = pd.bdate_range("2024-01-01", periods=10, tz="UTC")
    df = pd.DataFrame(
        {
            "open": range(10),
            "high": range(10),
            "low": range(10),
            "close": [float(x + 100) for x in range(10)],
            "volume": [1000] * 10,
        },
        index=dates,
    )
    df.attrs["currency"] = "USD"

    class FakeMarket:
        def get_bars(self, symbol, start, end):
            return df[(df.index >= pd.Timestamp(start, tz="UTC"))
                      & (df.index <= pd.Timestamp(end, tz="UTC"))]
        def get_latest(self, symbol):
            return df.iloc[-1]

    strategy = Strategy(
        name="test",
        universe=StaticUniverse(("AAPL",)),
        signals={},
        portfolio=EqualWeightOptimizer(),
    )

    engine = Engine()
    result = engine.run(
        strategy,
        market=FakeMarket(),
        broker=SimBroker(),
        start="2024-01-01",
        end="2024-01-15",
    )
    assert result.portfolio.currency == "USD"


def test_mixed_currency_rejected() -> None:
    """Engine should reject symbols with different currencies (v1)."""
    dates = pd.bdate_range("2024-01-01", periods=10, tz="UTC")

    def _make_df(currency: str) -> pd.DataFrame:
        df = pd.DataFrame(
            {
                "open": range(10),
                "high": range(10),
                "low": range(10),
                "close": [float(x + 100) for x in range(10)],
                "volume": [1000] * 10,
            },
            index=dates,
        )
        df.attrs["currency"] = currency
        return df

    class FakeMarket:
        def __init__(self):
            self.data = {"AAPL": _make_df("USD"), "600519": _make_df("CNY")}

        def get_bars(self, symbol, start, end):
            df = self.data[symbol]
            return df[(df.index >= pd.Timestamp(start, tz="UTC"))
                      & (df.index <= pd.Timestamp(end, tz="UTC"))]
        def get_latest(self, symbol):
            return self.data[symbol].iloc[-1]

    strategy = Strategy(
        name="test",
        universe=StaticUniverse(("AAPL", "600519")),
        signals={},
        portfolio=EqualWeightOptimizer(),
    )

    engine = Engine()
    with pytest.raises(ValueError, match="currency"):
        engine.run(
            strategy,
            market=FakeMarket(),
            broker=SimBroker(),
            start="2024-01-01",
            end="2024-01-15",
        )
