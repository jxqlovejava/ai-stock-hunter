"""Live trading tools — paper/live trading via LiveBroker."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from oxq.tools import session
from oxq.tools.registry import registry


def _load_dotenv() -> None:
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not os.environ.get(key):
            os.environ[key] = value


def _require_live() -> str | None:
    """Return error message if live connection is not established."""
    if session._live_broker is None:
        return "Not connected. Call live_connect first."
    return None


@registry.tool(
    name="live_connect",
    description="Connect to Alpaca brokerage for paper or live trading. Reads API keys from env vars or .env file.",
)
def live_connect(paper: bool = True) -> dict[str, Any]:
    """Initialize LiveBroker and AlpacaMarketDataProvider."""
    _load_dotenv()

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        return {
            "error": (
                "ALPACA_API_KEY and ALPACA_SECRET_KEY not set. "
                "Create a .env file in the project root or set environment variables. "
                "See .env.example for the format."
            ),
        }

    try:
        from oxq.contrib.alpaca.market_data import AlpacaMarketDataProvider
        from oxq.trade.live_broker import LiveBroker
    except ImportError:
        return {"error": "Live trading dependencies not installed. Run: pip install open-xquant[live]"}

    # Close existing connection if any
    if session._live_broker is not None:
        session._live_broker.close()

    broker = LiveBroker(api_key=api_key, secret_key=secret_key, paper=paper)
    market = AlpacaMarketDataProvider(api_key=api_key, secret_key=secret_key)

    session._live_broker = broker
    session._live_market = market

    account = broker.get_account()
    return {
        "status": "connected",
        "mode": "paper" if paper else "live",
        "account_status": account.get("status"),
        "equity": float(account.get("equity", 0)),
        "buying_power": float(account.get("buying_power", 0)),
    }


@registry.tool(
    name="live_account",
    description="Get account info: status, equity, buying power, cash.",
)
def live_account() -> dict[str, Any]:
    """Query account details from the brokerage."""
    err = _require_live()
    if err:
        return {"error": err}
    account = session._live_broker.get_account()  # type: ignore[union-attr]
    return {
        "status": account.get("status"),
        "equity": float(account.get("equity", 0)),
        "buying_power": float(account.get("buying_power", 0)),
        "cash": float(account.get("cash", 0)),
        "portfolio_value": float(account.get("portfolio_value", 0)),
    }


@registry.tool(
    name="live_positions",
    description="Get current portfolio positions from the brokerage.",
)
def live_positions() -> dict[str, Any]:
    """List all open positions."""
    err = _require_live()
    if err:
        return {"error": err}
    positions = session._live_broker.get_positions_detail()  # type: ignore[union-attr]
    result = []
    for p in positions:
        result.append({
            "symbol": p["symbol"],
            "qty": int(p["qty"]),
            "side": p.get("side", "long"),
            "avg_entry_price": float(p["avg_entry_price"]),
            "market_value": float(p.get("market_value", 0)),
            "unrealized_pl": float(p.get("unrealized_pl", 0)),
            "unrealized_plpc": float(p.get("unrealized_plpc", 0)),
            "current_price": float(p.get("current_price", 0)),
        })
    return {"total": len(result), "positions": result}


@registry.tool(
    name="live_bars",
    description="Fetch historical OHLCV bars for a symbol from Alpaca market data.",
)
def live_bars(
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1Day",
) -> dict[str, Any]:
    """Get historical bars via AlpacaMarketDataProvider."""
    if session._live_market is None:
        return {"error": "Not connected. Call live_connect first."}
    try:
        df = session._live_market.get_bars(symbol, start, end, timeframe)
    except Exception as e:
        return {"error": str(e)}
    bars = []
    for date, row in df.iterrows():
        bars.append({
            "date": str(date.date()),  # type: ignore[union-attr]
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
        })
    return {"symbol": symbol, "total_bars": len(bars), "bars": bars}


@registry.tool(
    name="live_generate_orders",
    description="Generate a trade plan from target weights using current positions and latest prices.",
)
def live_generate_orders(
    target_weights: dict[str, float],
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Generate PlannedOrders by comparing target weights to current positions."""
    err = _require_live()
    if err:
        return {"error": err}
    if session._live_market is None:
        return {"error": "Not connected. Call live_connect first."}

    from oxq.core.types import Position
    from oxq.trade.order_generator import generate_orders

    broker = session._live_broker  # type: ignore[assignment]
    market = session._live_market

    # Get account equity
    account = broker.get_account()
    equity = Decimal(account["equity"])

    # Get current positions
    raw_positions = broker.get_positions_detail()
    positions: dict[str, Position] = {}
    for p in raw_positions:
        positions[p["symbol"]] = Position(
            symbol=p["symbol"],
            shares=int(p["qty"]),
            avg_cost=Decimal(p["avg_entry_price"]),
        )

    # Get latest prices for all symbols
    all_symbols = list(set(target_weights.keys()) | set(positions.keys()))
    if symbols:
        all_symbols = list(set(all_symbols) | set(symbols))

    prices: dict[str, Decimal] = {}
    for sym in all_symbols:
        try:
            latest = market.get_latest(sym)
            prices[sym] = Decimal(str(latest["close"]))
        except Exception:
            continue

    weights = {s: Decimal(str(w)) for s, w in target_weights.items()}

    try:
        planned = generate_orders(
            target_weights=weights,
            positions=positions,
            prices=prices,
            total_capital=equity,
        )
    except Exception as e:
        return {"error": str(e)}

    orders = []
    for p in planned:
        orders.append({
            "symbol": p.order.symbol,
            "side": p.order.side,
            "shares": p.order.shares,
            "current_shares": p.current_shares,
            "target_shares": p.target_shares,
            "current_weight": float(p.current_weight),
            "target_weight": float(p.target_weight),
            "estimated_amount": float(p.estimated_amount),
        })
    return {
        "equity": float(equity),
        "total_orders": len(orders),
        "orders": orders,
    }


@registry.tool(
    name="live_submit_order",
    description="Submit an order to the brokerage. Supports market, limit, stop, stop_limit, and trailing_stop orders.",
)
def live_submit_order(
    symbol: str,
    side: str,
    shares: int,
    order_type: str = "market",
    limit_price: float | None = None,
    stop_price: float | None = None,
    trail_pct: float | None = None,
) -> dict[str, Any]:
    """Submit a single order via LiveBroker."""
    err = _require_live()
    if err:
        return {"error": err}

    from oxq.core.types import Order

    order = Order(
        symbol=symbol,
        side=side.upper(),
        shares=shares,
        order_type=order_type,
        limit_price=Decimal(str(limit_price)) if limit_price is not None else None,
        stop_price=Decimal(str(stop_price)) if stop_price is not None else None,
        trail_pct=trail_pct,
    )

    try:
        order_id = session._live_broker.submit_order(order)  # type: ignore[union-attr]
    except Exception as e:
        return {"error": str(e)}

    return {
        "order_id": order_id,
        "symbol": symbol,
        "side": side.upper(),
        "shares": shares,
        "order_type": order_type,
        "status": "submitted",
    }


@registry.tool(
    name="live_order_status",
    description="Get the status of a submitted order by its order ID.",
)
def live_order_status(order_id: str) -> dict[str, Any]:
    """Query order status from the brokerage."""
    err = _require_live()
    if err:
        return {"error": err}
    try:
        order = session._live_broker.get_order_status(order_id)  # type: ignore[union-attr]
    except Exception as e:
        return {"error": str(e)}
    result: dict[str, Any] = {
        "order_id": order.get("id"),
        "symbol": order.get("symbol"),
        "side": order.get("side"),
        "qty": order.get("qty"),
        "order_type": order.get("type"),
        "status": order.get("status"),
    }
    if order.get("filled_avg_price"):
        result["filled_avg_price"] = float(order["filled_avg_price"])
        result["filled_at"] = order.get("filled_at")
    return result


@registry.tool(
    name="live_open_orders",
    description="List all open (unfilled) orders, optionally filtered by symbol.",
)
def live_open_orders(symbol: str | None = None) -> dict[str, Any]:
    """List open orders tracked by LiveBroker."""
    err = _require_live()
    if err:
        return {"error": err}
    managed = session._live_broker.get_open_orders(symbol)  # type: ignore[union-attr]
    orders = []
    for m in managed:
        orders.append({
            "order_id": m.id,
            "symbol": m.order.symbol,
            "side": m.order.side,
            "shares": m.order.shares,
            "order_type": m.order.order_type,
            "status": m.status,
        })
    return {"total": len(orders), "orders": orders}


@registry.tool(
    name="live_cancel_order",
    description="Cancel all open orders for a symbol, optionally filtered by side (BUY/SELL).",
)
def live_cancel_order(symbol: str, side: str | None = None) -> dict[str, Any]:
    """Cancel orders via LiveBroker."""
    err = _require_live()
    if err:
        return {"error": err}
    try:
        canceled = session._live_broker.cancel_orders(symbol, side)  # type: ignore[union-attr]
    except Exception as e:
        return {"error": str(e)}
    orders = []
    for m in canceled:
        orders.append({
            "order_id": m.id,
            "symbol": m.order.symbol,
            "side": m.order.side,
            "shares": m.order.shares,
        })
    return {"canceled": len(orders), "orders": orders}
