"""Live Trading Demo — minimal example of using LiveBroker with Alpaca.

Prerequisites:
    pip install open-xquant[live]
    export ALPACA_API_KEY="your-paper-api-key"
    export ALPACA_SECRET_KEY="your-paper-secret-key"

Usage:
    python examples/app/live_trading_demo.py
"""

from __future__ import annotations

import time

from oxq.core.types import Order
from oxq.trade import LiveBroker


def main() -> None:
    # Connect to Alpaca Paper Trading (default)
    broker = LiveBroker(paper=True)
    print("Connected to Alpaca Paper Trading")

    try:
        # Submit a market buy order for 1 share of AAPL
        order = Order(symbol="AAPL", side="BUY", shares=1)
        order_id = broker.submit_order(order)
        print(f"Submitted order: {order_id}")

        # Wait for fill
        print("Waiting for fill...")
        for _ in range(30):
            fills = broker.get_fills()
            if fills:
                for fill in fills:
                    print(
                        f"  Filled: {fill.order.symbol} "
                        f"{fill.order.side} {fill.order.shares} shares "
                        f"@ ${fill.filled_price}"
                    )
                break
            time.sleep(1)
        else:
            print("  No fill received within 30 seconds")

        # Show open orders
        open_orders = broker.get_open_orders()
        print(f"Open orders: {len(open_orders)}")

    finally:
        broker.close()
        print("Done")


if __name__ == "__main__":
    main()
