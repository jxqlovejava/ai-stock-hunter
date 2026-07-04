"""Tests for live trading tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from oxq.tools import session
from oxq.tools.live import (
    live_account,
    live_bars,
    live_cancel_order,
    live_connect,
    live_generate_orders,
    live_open_orders,
    live_order_status,
    live_positions,
    live_submit_order,
)


class TestLiveConnect:
    def test_missing_keys(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
        result = live_connect()
        assert "error" in result
        assert "ALPACA_API_KEY" in result["error"]

    def test_success(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test-key")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")

        mock_broker = MagicMock()
        mock_broker.get_account.return_value = {
            "status": "ACTIVE",
            "equity": "100000",
            "buying_power": "200000",
        }
        mock_market = MagicMock()

        with (
            patch("oxq.trade.live_broker.LiveBroker", return_value=mock_broker),
            patch("oxq.contrib.alpaca.market_data.AlpacaMarketDataProvider", return_value=mock_market),
        ):
            result = live_connect(paper=True)

        assert result["status"] == "connected"
        assert result["mode"] == "paper"
        assert result["equity"] == 100000.0
        assert session._live_broker is mock_broker
        assert session._live_market is mock_market

        # Cleanup
        session._live_broker = None
        session._live_market = None


class TestRequireLive:
    def test_not_connected(self):
        session._live_broker = None
        result = live_account()
        assert "error" in result
        assert "live_connect" in result["error"]

    def test_positions_not_connected(self):
        session._live_broker = None
        result = live_positions()
        assert "error" in result


class TestLiveAccount:
    def test_success(self):
        mock_broker = MagicMock()
        mock_broker.get_account.return_value = {
            "status": "ACTIVE",
            "equity": "100000",
            "buying_power": "200000",
            "cash": "50000",
            "portfolio_value": "100000",
        }
        session._live_broker = mock_broker
        try:
            result = live_account()
            assert result["status"] == "ACTIVE"
            assert result["equity"] == 100000.0
            assert result["cash"] == 50000.0
        finally:
            session._live_broker = None


class TestLivePositions:
    def test_success(self):
        mock_broker = MagicMock()
        mock_broker.get_positions_detail.return_value = [
            {
                "symbol": "AAPL",
                "qty": "50",
                "side": "long",
                "avg_entry_price": "180.00",
                "market_value": "9500.00",
                "unrealized_pl": "500.00",
                "unrealized_plpc": "0.0556",
                "current_price": "190.00",
            },
        ]
        session._live_broker = mock_broker
        try:
            result = live_positions()
            assert result["total"] == 1
            assert result["positions"][0]["symbol"] == "AAPL"
            assert result["positions"][0]["qty"] == 50
        finally:
            session._live_broker = None


class TestLiveBars:
    def test_success(self):
        import pandas as pd

        df = pd.DataFrame(
            {"open": [150.0], "high": [155.0], "low": [149.0], "close": [153.0], "volume": [1000]},
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-02")]),
        )
        mock_market = MagicMock()
        mock_market.get_bars.return_value = df
        session._live_market = mock_market
        session._live_broker = MagicMock()  # needed for require check
        try:
            result = live_bars("AAPL", "2024-01-01", "2024-01-31")
            assert result["symbol"] == "AAPL"
            assert result["total_bars"] == 1
            assert result["bars"][0]["close"] == 153.0
        finally:
            session._live_broker = None
            session._live_market = None


class TestLiveSubmitOrder:
    def test_market_order(self):
        mock_broker = MagicMock()
        mock_broker.submit_order.return_value = "order-123"
        session._live_broker = mock_broker
        try:
            result = live_submit_order("AAPL", "BUY", 100)
            assert result["order_id"] == "order-123"
            assert result["status"] == "submitted"
            # Verify Order was constructed correctly
            call_args = mock_broker.submit_order.call_args[0][0]
            assert call_args.symbol == "AAPL"
            assert call_args.side == "BUY"
            assert call_args.shares == 100
            assert call_args.order_type == "market"
        finally:
            session._live_broker = None

    def test_limit_order(self):
        mock_broker = MagicMock()
        mock_broker.submit_order.return_value = "order-456"
        session._live_broker = mock_broker
        try:
            result = live_submit_order("AAPL", "BUY", 50, order_type="limit", limit_price=180.0)
            assert result["order_id"] == "order-456"
            call_args = mock_broker.submit_order.call_args[0][0]
            assert call_args.order_type == "limit"
            assert float(call_args.limit_price) == 180.0
        finally:
            session._live_broker = None


class TestLiveOrderStatus:
    def test_success(self):
        mock_broker = MagicMock()
        mock_broker.get_order_status.return_value = {
            "id": "order-123",
            "symbol": "AAPL",
            "side": "buy",
            "qty": "100",
            "type": "market",
            "status": "filled",
            "filled_avg_price": "185.50",
            "filled_at": "2024-01-15T10:30:00Z",
        }
        session._live_broker = mock_broker
        try:
            result = live_order_status("order-123")
            assert result["status"] == "filled"
            assert result["filled_avg_price"] == 185.50
        finally:
            session._live_broker = None


class TestLiveOpenOrders:
    def test_empty(self):
        mock_broker = MagicMock()
        mock_broker.get_open_orders.return_value = []
        session._live_broker = mock_broker
        try:
            result = live_open_orders()
            assert result["total"] == 0
        finally:
            session._live_broker = None


class TestLiveCancelOrder:
    def test_success(self):
        mock_managed = MagicMock()
        mock_managed.id = "order-123"
        mock_managed.order.symbol = "AAPL"
        mock_managed.order.side = "BUY"
        mock_managed.order.shares = 100
        mock_broker = MagicMock()
        mock_broker.cancel_orders.return_value = [mock_managed]
        session._live_broker = mock_broker
        try:
            result = live_cancel_order("AAPL")
            assert result["canceled"] == 1
        finally:
            session._live_broker = None


class TestLiveGenerateOrders:
    def test_success(self):
        import pandas as pd

        mock_broker = MagicMock()
        mock_broker.get_account.return_value = {"equity": "100000"}
        mock_broker.get_positions_detail.return_value = []
        mock_market = MagicMock()
        mock_market.get_latest.return_value = pd.Series({"close": 150.0})

        session._live_broker = mock_broker
        session._live_market = mock_market
        try:
            result = live_generate_orders({"AAPL": 0.5})
            assert result["equity"] == 100000.0
            assert result["total_orders"] == 1
            order = result["orders"][0]
            assert order["symbol"] == "AAPL"
            assert order["side"] == "BUY"
            # 100000 * 0.5 / 150 = 333 shares
            assert order["shares"] == 333
        finally:
            session._live_broker = None
            session._live_market = None
