"""Tests for BarSnapshot and PositionSnapshot dataclasses."""

from oxq.core.types import BarSnapshot, PositionSnapshot


def test_position_snapshot_is_frozen() -> None:
    ps = PositionSnapshot(shares=100, avg_cost=150.0)
    assert ps.shares == 100
    assert ps.avg_cost == 150.0


def test_bar_snapshot_is_frozen() -> None:
    snap = BarSnapshot(
        date="2024-01-02",
        target_weights={"AAPL": 0.6, "CASH": 0.4},
        adjusted_weights={"AAPL": 0.5, "CASH": 0.5},
        positions={"AAPL": PositionSnapshot(shares=100, avg_cost=150.0)},
        cash=50000.0,
        total_value=65000.0,
    )
    assert snap.target_weights["AAPL"] == 0.6
    assert snap.adjusted_weights["AAPL"] == 0.5
    assert snap.positions["AAPL"].shares == 100
    assert snap.cash == 50000.0
    assert snap.total_value == 65000.0
