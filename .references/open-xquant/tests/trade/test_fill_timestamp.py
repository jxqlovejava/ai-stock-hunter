"""Tests for Fill timestamp precision — Phase 3 of timezone-currency plan."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from oxq.core.types import BarSnapshot, Fill, Order
from oxq.trade.sim_broker import SimBroker


def test_fill_timestamp_has_timezone() -> None:
    """Fill.filled_at should contain ISO 8601 datetime with timezone offset."""
    dates = pd.bdate_range("2024-01-01", periods=2, tz="UTC")
    mktdata = {
        "AAPL": pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [105.0, 106.0],
                "low": [99.0, 100.0],
                "close": [104.0, 105.0],
                "volume": [1000, 1100],
            },
            index=dates,
        )
    }

    broker = SimBroker()
    broker.submit_order(Order(symbol="AAPL", side="BUY", shares=10))
    broker.on_bar_close(mktdata, dates[0])
    fills = broker.get_fills()

    assert len(fills) == 1
    fill = fills[0]
    # filled_at must be proper ISO 8601 with 'T' separator and timezone
    assert "T" in fill.filled_at, (
        f"Fill timestamp is not ISO 8601: {fill.filled_at}"
    )
    assert "+" in fill.filled_at or "Z" in fill.filled_at, (
        f"Fill timestamp lacks timezone: {fill.filled_at}"
    )


def test_fill_timestamp_from_stop_order() -> None:
    """Stop order fills should also have timezone in filled_at."""
    dates = pd.bdate_range("2024-01-01", periods=2, tz="UTC")
    mktdata = {
        "AAPL": pd.DataFrame(
            {
                "open": [100.0, 90.0],
                "high": [105.0, 95.0],
                "low": [99.0, 85.0],
                "close": [104.0, 88.0],
                "volume": [1000, 1100],
            },
            index=dates,
        )
    }

    broker = SimBroker()
    broker.submit_order(
        Order(symbol="AAPL", side="SELL", shares=10,
              order_type="stop", stop_price=Decimal("90"))
    )
    broker.on_bar_open(mktdata, dates[1])
    fills = broker.get_fills()

    assert len(fills) == 1
    assert "T" in fills[0].filled_at
    assert "+" in fills[0].filled_at or "Z" in fills[0].filled_at


def test_bar_snapshot_date_is_timestamp() -> None:
    """BarSnapshot.date should be typed as pd.Timestamp, not generic object."""
    snap = BarSnapshot(
        date=pd.Timestamp("2024-01-02", tz="UTC"),
        target_weights={"AAPL": 0.5},
        adjusted_weights={"AAPL": 0.5},
        positions={},
        cash=100000.0,
        total_value=100000.0,
    )
    assert isinstance(snap.date, pd.Timestamp)
