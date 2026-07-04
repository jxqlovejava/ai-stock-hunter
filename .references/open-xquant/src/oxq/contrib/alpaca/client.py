"""Alpaca API client — REST + WebSocket communication layer."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import websockets.asyncio.client


class AlpacaAPIError(Exception):
    """Raised when an Alpaca API call fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Alpaca API error {status_code}: {detail}")


_PAPER_REST = "https://paper-api.alpaca.markets"
_LIVE_REST = "https://api.alpaca.markets"
_PAPER_WS = "wss://paper-api.alpaca.markets/stream"
_LIVE_WS = "wss://api.alpaca.markets/stream"

logger = logging.getLogger(__name__)


class AlpacaClient:
    """Low-level Alpaca API client.

    Handles authentication, REST calls, and WebSocket streaming.
    All REST methods return raw dicts — business logic lives in LiveBroker.

    Parameters
    ----------
    api_key : str or None
        Alpaca API key. Falls back to ``ALPACA_API_KEY`` env var.
    secret_key : str or None
        Alpaca secret key. Falls back to ``ALPACA_SECRET_KEY`` env var.
    paper : bool
        If True (default), use Paper Trading endpoints.
    """

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        paper: bool = True,
    ) -> None:
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self._secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        if not self._api_key or not self._secret_key:
            msg = "API key and secret key required. Set ALPACA_API_KEY/ALPACA_SECRET_KEY or pass explicitly."
            raise ValueError(msg)

        self._base_url = _PAPER_REST if paper else _LIVE_REST
        self._paper = paper
        self._stream_running = False
        self._stream_thread: threading.Thread | None = None
        self._http = httpx.Client(
            base_url=self._base_url,
            headers={
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._secret_key,
            },
            timeout=30.0,
        )

    # -- REST methods ----------------------------------------------------------

    def submit_order(self, order_params: dict[str, Any]) -> dict[str, Any]:
        """Submit an order via POST /v2/orders."""
        resp = self._http.post("/v2/orders", json=order_params)
        return self._handle(resp)

    def get_order(self, order_id: str) -> dict[str, Any]:
        """Get order status via GET /v2/orders/{id}."""
        resp = self._http.get(f"/v2/orders/{order_id}")
        return self._handle(resp)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an order via DELETE /v2/orders/{id}."""
        resp = self._http.delete(f"/v2/orders/{order_id}")
        if resp.status_code == 204:
            return {}
        return self._handle(resp)

    def list_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """List open orders via GET /v2/orders."""
        params: dict[str, str] = {"status": "open"}
        if symbol:
            params["symbols"] = symbol
        resp = self._http.get("/v2/orders", params=params)
        return self._handle(resp)

    def get_positions(self) -> list[dict[str, Any]]:
        """List positions via GET /v2/positions."""
        resp = self._http.get("/v2/positions")
        return self._handle(resp)

    def get_account(self) -> dict[str, Any]:
        """Get account info via GET /v2/account."""
        resp = self._http.get("/v2/account")
        return self._handle(resp)

    # -- WebSocket streaming ---------------------------------------------------

    def start_trade_stream(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Start a daemon thread that streams trade updates via WebSocket.

        Parameters
        ----------
        callback : callable
            Called with each parsed trade-update message dict.
        """
        ws_url = _PAPER_WS if self._paper else _LIVE_WS
        self._stream_running = True
        self._stream_thread = threading.Thread(
            target=_run_stream,
            args=(ws_url, self._api_key, self._secret_key, callback, self),
            daemon=True,
        )
        self._stream_thread.start()

    def stop_trade_stream(self) -> None:
        """Signal the streaming thread to stop."""
        self._stream_running = False

    @staticmethod
    def _on_trade_update(msg: dict[str, Any], callback: Callable[[dict[str, Any]], None]) -> None:
        """Route trade_updates messages to *callback*."""
        if msg.get("stream") == "trade_updates":
            callback(msg)

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()

    # -- Helpers ---------------------------------------------------------------

    def _handle(self, resp: httpx.Response) -> Any:
        """Check response status and return JSON."""
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                detail = resp.text
            raise AlpacaAPIError(resp.status_code, detail)
        return resp.json()


def _run_stream(
    ws_url: str,
    api_key: str,
    secret_key: str,
    callback: Callable[[dict[str, Any]], None],
    client: AlpacaClient,
) -> None:
    """Connect to Alpaca WebSocket and stream trade updates.

    Reconnects with exponential backoff (1 s -> 30 s max) on failure.
    """
    backoff = 1.0
    max_backoff = 30.0

    async def _stream() -> None:
        nonlocal backoff
        async with websockets.asyncio.client.connect(ws_url) as ws:
            # Authenticate
            await ws.send(json.dumps({"action": "auth", "key": api_key, "secret": secret_key}))
            auth_resp = json.loads(await ws.recv())
            if auth_resp.get("data", {}).get("status") != "authorized":
                raise ConnectionError(f"Alpaca auth failed: {auth_resp}")

            # Subscribe to trade_updates
            await ws.send(json.dumps({"action": "listen", "data": {"streams": ["trade_updates"]}}))

            backoff = 1.0  # reset on successful connection
            while client._stream_running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except TimeoutError:
                    continue
                msg = json.loads(raw)
                AlpacaClient._on_trade_update(msg, callback)

    while client._stream_running:
        try:
            asyncio.run(_stream())
        except Exception:
            if not client._stream_running:
                break
            logger.warning("WebSocket disconnected, reconnecting in %.1fs", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
