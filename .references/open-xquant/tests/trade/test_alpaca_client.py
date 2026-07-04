"""Tests for AlpacaClient REST methods."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from oxq.contrib.alpaca.client import AlpacaAPIError, AlpacaClient


class TestAlpacaClientInit:
    def test_paper_base_url(self):
        client = AlpacaClient(api_key="test", secret_key="secret", paper=True)
        assert "paper-api" in client._base_url

    def test_live_base_url(self):
        client = AlpacaClient(api_key="test", secret_key="secret", paper=False)
        assert "paper-api" not in client._base_url

    def test_env_vars_fallback(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "env_key")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "env_secret")
        client = AlpacaClient()
        assert client._api_key == "env_key"
        assert client._secret_key == "env_secret"

    def test_constructor_overrides_env(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "env_key")
        client = AlpacaClient(api_key="explicit", secret_key="explicit_s")
        assert client._api_key == "explicit"

    def test_missing_credentials_raises(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
        with pytest.raises(ValueError, match="API key"):
            AlpacaClient()


class TestSubmitOrder:
    def test_submit_market_order(self):
        client = AlpacaClient(api_key="k", secret_key="s")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "alpaca-order-1",
            "status": "accepted",
        }
        with patch.object(client._http, "post", return_value=mock_response):
            result = client.submit_order({
                "symbol": "AAPL",
                "side": "buy",
                "qty": "100",
                "type": "market",
                "time_in_force": "day",
            })
        assert result["id"] == "alpaca-order-1"

    def test_submit_order_api_error(self):
        client = AlpacaClient(api_key="k", secret_key="s")
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.json.return_value = {"message": "invalid qty"}
        mock_response.raise_for_status.side_effect = Exception("422")
        with patch.object(client._http, "post", return_value=mock_response):
            with pytest.raises(AlpacaAPIError):
                client.submit_order({"symbol": "AAPL"})


class TestGetOrder:
    def test_get_order(self):
        client = AlpacaClient(api_key="k", secret_key="s")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "abc123",
            "status": "filled",
            "filled_avg_price": "150.25",
        }
        with patch.object(client._http, "get", return_value=mock_response):
            result = client.get_order("abc123")
        assert result["status"] == "filled"


class TestCancelOrder:
    def test_cancel_order(self):
        client = AlpacaClient(api_key="k", secret_key="s")
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.json.return_value = {}
        with patch.object(client._http, "delete", return_value=mock_response):
            result = client.cancel_order("abc123")
        assert result == {}


class TestListOpenOrders:
    def test_list_all(self):
        client = AlpacaClient(api_key="k", secret_key="s")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "o1", "symbol": "AAPL"},
            {"id": "o2", "symbol": "GOOG"},
        ]
        with patch.object(client._http, "get", return_value=mock_response):
            result = client.list_open_orders()
        assert len(result) == 2

    def test_list_by_symbol(self):
        client = AlpacaClient(api_key="k", secret_key="s")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "o1", "symbol": "AAPL"}]
        with patch.object(client._http, "get", return_value=mock_response) as mock_get:
            result = client.list_open_orders(symbol="AAPL")
        assert len(result) == 1
        mock_get.assert_called_once_with(
            "/v2/orders", params={"status": "open", "symbols": "AAPL"},
        )


class TestGetPositions:
    def test_get_positions(self):
        client = AlpacaClient(api_key="k", secret_key="s")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"symbol": "AAPL", "qty": "10", "avg_entry_price": "150.00"},
            {"symbol": "GOOG", "qty": "5", "avg_entry_price": "2800.00"},
        ]
        with patch.object(client._http, "get", return_value=mock_response):
            result = client.get_positions()
        assert len(result) == 2
        assert result[0]["symbol"] == "AAPL"


class TestGetAccount:
    def test_get_account(self):
        client = AlpacaClient(api_key="k", secret_key="s")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "account-1",
            "status": "ACTIVE",
            "equity": "100000.00",
        }
        with patch.object(client._http, "get", return_value=mock_response):
            result = client.get_account()
        assert result["status"] == "ACTIVE"
        assert result["equity"] == "100000.00"


class TestTradeStream:
    def test_start_and_stop(self):
        """Verify start_trade_stream launches a thread and stop cleans up."""
        client = AlpacaClient(api_key="k", secret_key="s")
        fills: list = []
        gate = threading.Event()

        def _blocking_run(*args, **kwargs):
            gate.wait()

        with patch("oxq.contrib.alpaca.client._run_stream", side_effect=_blocking_run):
            client.start_trade_stream(lambda msg: fills.append(msg))
            assert client._stream_thread is not None
            assert client._stream_thread.is_alive()
            client.stop_trade_stream()
            assert not client._stream_running
            gate.set()  # unblock so thread exits cleanly

    def test_callback_receives_fill(self):
        """Verify the callback is invoked with parsed trade update."""
        client = AlpacaClient(api_key="k", secret_key="s")
        fills: list = []
        fill_msg = {
            "stream": "trade_updates",
            "data": {
                "event": "fill",
                "order": {"id": "abc", "filled_avg_price": "150.00"},
            },
        }
        client._on_trade_update(fill_msg, lambda msg: fills.append(msg))
        assert len(fills) == 1
        assert fills[0]["data"]["event"] == "fill"


class TestHandleError:
    def test_non_json_error_response(self):
        """When resp.json() raises (e.g. HTML 502), _handle falls back to resp.text."""
        client = AlpacaClient(api_key="k", secret_key="s")
        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.text = "<html>Bad Gateway</html>"
        with pytest.raises(AlpacaAPIError, match="Bad Gateway"):
            client._handle(mock_response)
