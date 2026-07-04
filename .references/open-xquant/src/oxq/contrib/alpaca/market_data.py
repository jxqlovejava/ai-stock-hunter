"""AlpacaMarketDataProvider — market data from Alpaca Data API."""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

_DATA_BASE_URL = "https://data.alpaca.markets"


class AlpacaMarketDataProvider:
    """MarketDataProvider backed by Alpaca's Market Data API.

    Uses a separate httpx.Client pointing to data.alpaca.markets
    (distinct from the Trading API used by AlpacaClient).

    Parameters
    ----------
    api_key : str or None
        Alpaca API key. Falls back to ALPACA_API_KEY env var.
    secret_key : str or None
        Alpaca secret key. Falls back to ALPACA_SECRET_KEY env var.
    feed : str
        Data feed. ``"iex"`` (default, free) or ``"sip"`` (paid, all exchanges).
    """

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        feed: str = "iex",
    ) -> None:
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self._secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        if not self._api_key or not self._secret_key:
            msg = "API key and secret key required. Set ALPACA_API_KEY/ALPACA_SECRET_KEY or pass explicitly."
            raise ValueError(msg)

        self._feed = feed
        self._http = httpx.Client(
            base_url=_DATA_BASE_URL,
            headers={
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._secret_key,
            },
            timeout=30.0,
        )

    def get_bars(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str = "1Day",
    ) -> pd.DataFrame:
        """Fetch historical OHLCV bars for a single symbol.

        Conforms to the ``MarketDataProvider`` protocol so that this
        provider can be passed directly to ``Engine``.

        Parameters
        ----------
        symbol : str
            Ticker symbol.
        start, end : str
            Date range (ISO format).
        timeframe : str
            Bar timeframe. Default "1Day".

        Returns
        -------
        pd.DataFrame
            DataFrame with columns [open, high, low, close, volume].
        """
        return self.get_bars_multi([symbol], start, end, timeframe)[symbol]

    def get_latest(self, symbol: str) -> pd.Series:
        """Fetch the latest bar for a symbol.

        Conforms to the ``MarketDataProvider`` protocol.

        Parameters
        ----------
        symbol : str
            Ticker symbol.

        Returns
        -------
        pd.Series
            Latest bar as a Series with keys [open, high, low, close, volume].
        """
        return self.get_latest_multi([symbol])[symbol]

    def get_bars_multi(
        self,
        symbols: list[str],
        start: str,
        end: str,
        timeframe: str = "1Day",
    ) -> dict[str, pd.DataFrame]:
        """Fetch historical OHLCV bars for multiple symbols in one request.

        Parameters
        ----------
        symbols : list[str]
            Ticker symbols.
        start, end : str
            Date range (ISO format).
        timeframe : str
            Bar timeframe. Default "1Day".

        Returns
        -------
        dict[str, pd.DataFrame]
            Per-symbol DataFrames with columns [open, high, low, close, volume].
        """
        params: dict[str, str] = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "limit": "10000",
            "adjustment": "raw",
            "feed": self._feed,
        }
        resp = self._http.get("/v2/stocks/bars", params=params)
        data = self._handle(resp)
        return _parse_bars_response(data)

    def get_latest_multi(
        self,
        symbols: list[str],
    ) -> dict[str, pd.Series]:
        """Fetch the latest bar for multiple symbols in one request.

        Parameters
        ----------
        symbols : list[str]
            Ticker symbols.

        Returns
        -------
        dict[str, pd.Series]
            Latest bar per symbol as a Series.
        """
        params: dict[str, str] = {"symbols": ",".join(symbols), "feed": self._feed}
        resp = self._http.get("/v2/stocks/bars/latest", params=params)
        data = self._handle(resp)
        result: dict[str, pd.Series] = {}
        bars = data.get("bars", {})
        for sym, bar in bars.items():
            df = _bar_to_df([bar])
            result[sym] = df.iloc[0]
        return result

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()

    def _handle(self, resp: httpx.Response) -> Any:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                detail = resp.text
            msg = f"Alpaca Data API error {resp.status_code}: {detail}"
            raise RuntimeError(msg)
        return resp.json()


def _parse_bars_response(data: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Parse Alpaca multi-symbol bars response into DataFrames."""
    result: dict[str, pd.DataFrame] = {}
    bars = data.get("bars", {})
    for symbol, bar_list in bars.items():
        result[symbol] = _bar_to_df(bar_list)
    return result


def _bar_to_df(bars: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert a list of Alpaca bar dicts to a DataFrame."""
    records = []
    for b in bars:
        records.append({
            "open": b["o"],
            "high": b["h"],
            "low": b["l"],
            "close": b["c"],
            "volume": b["v"],
            "timestamp": pd.Timestamp(b["t"]),
        })
    df = pd.DataFrame(records)
    df = df.set_index("timestamp")
    df.index = df.index.normalize()  # strip time, keep date
    # Preserve UTC timezone from Alpaca API
    return df
