"""Integration tests for LiveBroker against Alpaca Paper Trading.

Run with: uv run pytest tests/trade/test_alpaca_integration.py -v -m integration
Requires: ALPACA_API_KEY and ALPACA_SECRET_KEY env vars set.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from oxq.core.types import Order
from oxq.trade.live_broker import LiveBroker


@pytest.mark.integration
class TestAlpacaPaperTrading:
    @pytest.fixture
    def broker(self):
        b = LiveBroker(paper=True)
        yield b
        b.close()

    def test_submit_and_fill_market_order(self, broker):
        """Submit a small market buy, wait for fill."""
        order = Order(symbol="AAPL", side="BUY", shares=1)
        oid = broker.submit_order(order)
        assert oid

        fills = []
        for _ in range(30):
            fills = broker.get_fills()
            if fills:
                break
            time.sleep(1)

        assert len(fills) == 1
        assert fills[0].order.symbol == "AAPL"
        assert fills[0].filled_price > Decimal("0")

    def test_submit_and_cancel_limit_order(self, broker):
        """Submit a limit order far from market, then cancel it."""
        order = Order(
            symbol="AAPL",
            side="BUY",
            shares=1,
            order_type="limit",
            limit_price=Decimal("1.00"),
        )
        oid = broker.submit_order(order)
        assert oid

        canceled = broker.cancel_orders("AAPL")
        assert len(canceled) == 1
        assert canceled[0].status == "canceled"
