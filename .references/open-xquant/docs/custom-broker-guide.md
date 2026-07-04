# Custom Broker Implementation Guide

This guide walks you through implementing a custom `Broker` for a new brokerage.
Use the Alpaca reference implementation (`AlpacaClient` + `LiveBroker`) as a model.

## Overview: The Two-Layer Pattern

oxq separates brokerage integration into two layers:

| Layer | Responsibility | Example |
|-------|---------------|---------|
| **Client** | Raw API communication (REST, WebSocket, auth) | `AlpacaClient` |
| **Broker** | Satisfies the `Broker` Protocol, maps oxq types, manages `OrderBook` | `LiveBroker` |

The **Client** knows nothing about oxq types. It sends dicts and returns dicts.
The **Broker** translates between oxq's `Order`/`Fill` types and the client's raw API,
and delegates order lifecycle tracking to the reusable `OrderBook`.

```
Strategy -> Engine -> Broker.submit_order(Order)
                         |-> Client.submit_order(dict)  # raw API call
                         |-> OrderBook.add(order)        # local tracking

Exchange -> Client (WebSocket) -> Broker._on_fill_event
                                     |-> OrderBook.fill(managed, price, date)
                                     |-> append to _fills list
```

## Broker Protocol Reference

Your broker class must implement all methods from `oxq.core.types.Broker`:

```python
class Broker(OrderRouter, FillReceiver, Protocol):
    def submit_order(self, order: Order) -> str: ...
    def get_fills(self) -> list[Fill]: ...
    def on_bar_open(self, mktdata: dict[str, pd.DataFrame], date: pd.Timestamp) -> None: ...
    def on_bar_close(self, mktdata: dict[str, pd.DataFrame], date: pd.Timestamp) -> None: ...
    def get_open_orders(self, symbol: str | None = None) -> list[ManagedOrder]: ...
    def cancel_orders(self, symbol: str, side: str | None = None) -> list[ManagedOrder]: ...
    def cap_pending_sells(self, symbol: str, max_shares: int) -> None: ...
```

### Method details

| Method | When called | What to do |
|--------|------------|------------|
| `submit_order` | Strategy generates an order | Convert `Order` to broker API params, send to exchange, track in `OrderBook`, return broker order ID |
| `get_fills` | Engine collects fills each bar | Return and **clear** accumulated `Fill` objects |
| `on_bar_open` | Start of each bar | No-op for live brokers (exchange processes orders) |
| `on_bar_close` | End of each bar | No-op for live brokers |
| `get_open_orders` | Engine checks stale orders | Delegate to `OrderBook.get_open_orders` |
| `cancel_orders` | Engine cancels stale orders | Cancel on exchange **and** in local `OrderBook` |
| `cap_pending_sells` | Position reduced, sells exceed holdings | Cancel oversized sells on exchange, cap in `OrderBook`, re-submit capped orders |

## Order/Fill Mapping

When converting between oxq types and your broker's API, map these fields:

### Order (oxq -> broker API)

| oxq `Order` field | Typical broker field | Notes |
|-------------------|---------------------|-------|
| `symbol` | `symbol` / `instrument_id` | May need ticker-to-ID lookup |
| `side` | `side` | oxq uses `"BUY"` / `"SELL"` (uppercase); most APIs want lowercase |
| `shares` | `qty` / `quantity` | Integer number of shares |
| `order_type` | `type` / `order_type` | `"market"`, `"limit"`, `"stop"`, `"stop_limit"`, `"trailing_stop"` |
| `limit_price` | `limit_price` | `Decimal`; convert to string for most APIs |
| `stop_price` | `stop_price` | `Decimal`; only for stop/stop_limit orders |
| `trail_pct` | `trail_percent` | Float 0.0-1.0 in oxq; some APIs want percentage (multiply by 100) |

### Fill (broker API -> oxq)

| Broker response field | oxq `Fill` field | Notes |
|----------------------|-----------------|-------|
| `filled_avg_price` | `filled_price` | Convert to `Decimal` |
| `filled_at` / `timestamp` | `filled_at` | ISO date string |
| Fee from API or compute | `fee` | `Decimal`; default `Decimal("0")` |
| — | `order` | The original `Order` object from the `ManagedOrder` |

## Fill Delivery Options

| Approach | Pros | Cons |
|----------|------|------|
| **WebSocket** (like Alpaca) | Real-time, low latency, exchange pushes fills to you | Requires reconnection logic, thread management |
| **Polling** | Simpler implementation, no WebSocket dependency | Higher latency, wastes API calls, may miss rapid fills between polls |

**Recommendation:** Use WebSocket if your broker supports it. If polling, call it from
`on_bar_open` or `on_bar_close` to check for fills each bar.

## Reusable Components

oxq provides these types that you should use directly (do **not** reimplement them):

| Component | Import | Purpose |
|-----------|--------|---------|
| `Order` | `oxq.core.types` | Immutable order request (frozen dataclass) |
| `Fill` | `oxq.core.types` | Immutable fill record |
| `Position` | `oxq.core.types` | Immutable position snapshot |
| `ManagedOrder` | `oxq.portfolio.orderbook` | Mutable order with lifecycle state |
| `OrderBook` | `oxq.portfolio.orderbook` | Tracks orders, handles dedup, fill, cancel, cap |

The `OrderBook` handles all local order lifecycle management. Your broker should
create one instance and delegate to it for `add`, `fill`, `cancel_orders`,
`cap_pending_sells`, and `get_open_orders`.

## Common Pitfalls

### Partial fills

oxq's current `OrderBook.fill()` marks the order as fully filled. If your broker
supports partial fills, you need to accumulate partial quantities and only call
`OrderBook.fill()` when the order is fully filled (or handle partial fill logic
in your broker layer).

### Reconnection

WebSocket connections drop. Implement exponential backoff with a cap
(see `AlpacaClient._run_stream` for a reference: 1s initial, doubling to 30s max).
Run the WebSocket in a daemon thread so it does not block the main engine loop.

### ID mapping

You must maintain a `dict[str, ManagedOrder]` mapping broker order IDs to local
`ManagedOrder` objects. When a fill arrives via WebSocket, look up the managed order
by broker ID. If the ID is not found (e.g., order submitted before reconnect),
log a warning and skip.

### Decimal precision

Always use `Decimal` for prices and fees, never `float`. Convert broker response
strings directly: `Decimal(response["price"])`. This avoids floating-point
rounding errors that compound across many trades.

### Thread safety

If your fill callback runs on a WebSocket thread while the engine reads `get_fills()`
on the main thread, protect `_fills` with a lock. The reference implementation keeps
things simple because Alpaca's WebSocket thread only appends and `get_fills()` does
a swap-and-clear, but more complex brokers may need explicit synchronization.

## Minimal Skeleton

```python
"""Skeleton broker for a custom brokerage."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from oxq.core.types import Fill, Order
from oxq.portfolio.orderbook import ManagedOrder, OrderBook


class MyClient:
    """Low-level API client for MyBrokerage. Knows nothing about oxq types."""

    def __init__(self, api_key: str) -> None:
        # Set up HTTP client, authenticate
        ...

    def submit_order(self, params: dict[str, Any]) -> dict[str, Any]:
        # POST to broker API, return response dict with order ID
        ...

    def cancel_order(self, order_id: str) -> None:
        # DELETE/cancel on broker API
        ...

    def start_stream(self, callback):
        # Start WebSocket in daemon thread, call callback(msg) on each fill
        ...

    def stop_stream(self) -> None:
        ...


class MyBroker:
    """Broker Protocol implementation for MyBrokerage."""

    def __init__(self, api_key: str) -> None:
        self._client = MyClient(api_key)
        self._order_book = OrderBook()
        self._fills: list[Fill] = []
        self._id_map: dict[str, ManagedOrder] = {}
        self._client.start_stream(self._on_message)

    # -- OrderRouter -----------------------------------------------------------

    def submit_order(self, order: Order) -> str:
        params = _order_to_my_broker(order)
        resp = self._client.submit_order(params)
        broker_id = resp["order_id"]
        managed = self._order_book.add(order, created_at="")
        managed.id = broker_id
        self._id_map[broker_id] = managed
        return broker_id

    # -- FillReceiver ----------------------------------------------------------

    def get_fills(self) -> list[Fill]:
        fills = list(self._fills)
        self._fills.clear()
        return fills

    # -- Lifecycle hooks (no-op for live) --------------------------------------

    def on_bar_open(self, mktdata: dict[str, pd.DataFrame], date: pd.Timestamp) -> None:
        pass

    def on_bar_close(self, mktdata: dict[str, pd.DataFrame], date: pd.Timestamp) -> None:
        pass

    # -- Order management ------------------------------------------------------

    def get_open_orders(self, symbol: str | None = None) -> list[ManagedOrder]:
        return self._order_book.get_open_orders(symbol)

    def cancel_orders(self, symbol: str, side: str | None = None) -> list[ManagedOrder]:
        to_cancel = self._order_book.get_open_orders(symbol)
        if side:
            to_cancel = [m for m in to_cancel if m.order.side == side]
        for managed in to_cancel:
            self._client.cancel_order(managed.id)
        return self._order_book.cancel_orders(symbol, side)

    def cap_pending_sells(self, symbol: str, max_shares: int) -> None:
        # Cancel oversized sells, cap in OrderBook, re-submit
        # See LiveBroker.cap_pending_sells for full reference
        self._order_book.cap_pending_sells(symbol, max_shares)

    # -- Fill callback ---------------------------------------------------------

    def _on_message(self, msg: dict[str, Any]) -> None:
        broker_id = msg["order_id"]
        managed = self._id_map.get(broker_id)
        if managed is None:
            return
        price = Decimal(msg["fill_price"])
        fill = self._order_book.fill(managed, price, msg["timestamp"])
        self._fills.append(fill)

    def close(self) -> None:
        self._client.stop_stream()


def _order_to_my_broker(order: Order) -> dict[str, str]:
    """Convert oxq Order to MyBrokerage API parameters."""
    params: dict[str, str] = {
        "symbol": order.symbol,
        "side": order.side.lower(),
        "quantity": str(order.shares),
        "type": order.order_type,
    }
    if order.limit_price is not None:
        params["limit_price"] = str(order.limit_price)
    if order.stop_price is not None:
        params["stop_price"] = str(order.stop_price)
    return params
```

## Reference Implementation

For a complete working example, see:

- **`src/oxq/contrib/alpaca/client.py`** — Client layer (REST + WebSocket)
- **`src/oxq/trade/live_broker.py`** — Broker layer (Protocol implementation)
- **`src/oxq/portfolio/orderbook.py`** — Reusable order lifecycle management
- **`src/oxq/core/types.py`** — `Order`, `Fill`, `Position`, `Broker` Protocol
