"""Tests for AlpacaMarketDataProvider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from oxq.contrib.alpaca.market_data import AlpacaMarketDataProvider

_BARS_RESPONSE = {
    "bars": {
        "AAPL": [
            {"t": "2024-01-02T05:00:00Z", "o": 150.0, "h": 155.0, "l": 149.0, "c": 153.0, "v": 1000},
            {"t": "2024-01-03T05:00:00Z", "o": 153.0, "h": 156.0, "l": 152.0, "c": 154.0, "v": 1200},
        ],
    },
    "next_page_token": None,
}

_LATEST_RESPONSE = {
    "bars": {
        "AAPL": {"t": "2024-01-04T05:00:00Z", "o": 154.0, "h": 157.0, "l": 153.0, "c": 155.0, "v": 800},
    },
}


class TestGetBars:
    """get_bars(symbol, ...) returns a single DataFrame (protocol-compatible)."""

    def test_returns_dataframe(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _BARS_RESPONSE
        with patch.object(provider._http, "get", return_value=mock_resp):
            result = provider.get_bars("AAPL", "2024-01-02", "2024-01-03")
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert len(result) == 2

    def test_datetime_index(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _BARS_RESPONSE
        with patch.object(provider._http, "get", return_value=mock_resp):
            result = provider.get_bars("AAPL", "2024-01-02", "2024-01-03")
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_index_is_tz_aware(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _BARS_RESPONSE
        with patch.object(provider._http, "get", return_value=mock_resp):
            result = provider.get_bars("AAPL", "2024-01-02", "2024-01-03")
        assert result.index.tz is not None


class TestGetLatest:
    """get_latest(symbol) returns a single Series (protocol-compatible)."""

    def test_returns_series(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _LATEST_RESPONSE
        with patch.object(provider._http, "get", return_value=mock_resp):
            result = provider.get_latest("AAPL")
        assert isinstance(result, pd.Series)
        assert result["close"] == 155.0


class TestGetBarsMulti:
    """get_bars_multi(symbols, ...) returns dict[str, DataFrame]."""

    def test_returns_dict_of_dataframes(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _BARS_RESPONSE
        with patch.object(provider._http, "get", return_value=mock_resp):
            result = provider.get_bars_multi(["AAPL"], "2024-01-02", "2024-01-03")
        assert "AAPL" in result
        assert isinstance(result["AAPL"], pd.DataFrame)
        assert len(result["AAPL"]) == 2


class TestGetLatestMulti:
    """get_latest_multi(symbols) returns dict[str, Series]."""

    def test_returns_dict_of_series(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _LATEST_RESPONSE
        with patch.object(provider._http, "get", return_value=mock_resp):
            result = provider.get_latest_multi(["AAPL"])
        assert "AAPL" in result
        assert isinstance(result["AAPL"], pd.Series)
        assert result["AAPL"]["close"] == 155.0


class TestInit:
    def test_base_url_is_data_api(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s")
        assert "data.alpaca.markets" in str(provider._http.base_url)

    def test_env_vars_fallback(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "env_key")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "env_secret")
        provider = AlpacaMarketDataProvider()
        assert provider._api_key == "env_key"

    def test_default_feed_is_iex(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s")
        assert provider._feed == "iex"

    def test_custom_feed(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s", feed="sip")
        assert provider._feed == "sip"


class TestFeedParam:
    def test_get_bars_passes_feed(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s", feed="sip")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _BARS_RESPONSE
        with patch.object(provider._http, "get", return_value=mock_resp) as mock_get:
            provider.get_bars("AAPL", "2024-01-02", "2024-01-03")
        call_params = mock_get.call_args[1]["params"]
        assert call_params["feed"] == "sip"

    def test_get_latest_passes_feed(self):
        provider = AlpacaMarketDataProvider(api_key="k", secret_key="s")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _LATEST_RESPONSE
        with patch.object(provider._http, "get", return_value=mock_resp) as mock_get:
            provider.get_latest("AAPL")
        call_params = mock_get.call_args[1]["params"]
        assert call_params["feed"] == "iex"
