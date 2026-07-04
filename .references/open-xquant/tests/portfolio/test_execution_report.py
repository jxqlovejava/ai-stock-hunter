"""Tests for ExecutionReport — sim vs live fill comparison."""

from __future__ import annotations

from decimal import Decimal

from oxq.core.types import Fill, Order
from oxq.portfolio.execution_report import ExecutionReport


def _fill(symbol, side, shares, price, date, fee="0"):
    return Fill(
        order=Order(symbol=symbol, side=side, shares=shares),
        filled_price=Decimal(price),
        filled_at=date,
        fee=Decimal(fee),
    )


class TestExecutionReport:
    def test_matched_trade(self):
        """Same symbol+date+side in both -> comparison with slippage."""
        sim = [_fill("AAPL", "BUY", 100, "150.00", "2024-01-02")]
        live = [_fill("AAPL", "BUY", 100, "150.30", "2024-01-02")]
        report = ExecutionReport(sim_fills=sim, live_fills=live)
        assert len(report.comparisons) == 1
        c = report.comparisons[0]
        assert c.sim_avg_price == Decimal("150.00")
        assert c.live_avg_price == Decimal("150.30")
        assert c.shares_diff == 0
        assert c.price_slippage == Decimal("0.30") / Decimal("150.00")

    def test_sim_only(self):
        """Trade in sim but not live."""
        sim = [_fill("AAPL", "BUY", 100, "150.00", "2024-01-02")]
        report = ExecutionReport(sim_fills=sim, live_fills=[])
        assert len(report.comparisons) == 1
        c = report.comparisons[0]
        assert c.live_shares == 0
        assert c.live_avg_price == Decimal("0")

    def test_live_only(self):
        """Trade in live but not sim."""
        live = [_fill("GOOG", "SELL", 50, "180.00", "2024-01-03")]
        report = ExecutionReport(sim_fills=[], live_fills=live)
        assert len(report.comparisons) == 1
        c = report.comparisons[0]
        assert c.sim_shares == 0

    def test_aggregation(self):
        """Multiple fills same symbol+date+side -> aggregated."""
        sim = [_fill("AAPL", "BUY", 100, "150.00", "2024-01-02")]
        live = [
            _fill("AAPL", "BUY", 60, "150.20", "2024-01-02"),
            _fill("AAPL", "BUY", 40, "150.40", "2024-01-02"),
        ]
        report = ExecutionReport(sim_fills=sim, live_fills=live)
        c = report.comparisons[0]
        assert c.live_shares == 100
        # VWAP: (60*150.20 + 40*150.40) / 100 = 150.28
        assert c.live_avg_price == Decimal("150.28")

    def test_summary(self):
        """Summary includes counts and avg slippage."""
        sim = [
            _fill("AAPL", "BUY", 100, "150.00", "2024-01-02"),
            _fill("GOOG", "BUY", 50, "180.00", "2024-01-02"),
        ]
        live = [
            _fill("AAPL", "BUY", 100, "150.30", "2024-01-02"),
        ]
        report = ExecutionReport(sim_fills=sim, live_fills=live)
        s = report.summary()
        assert s["total_trades"] == 2
        assert s["matched_trades"] == 1
        assert s["sim_only_trades"] == 1
        assert s["live_only_trades"] == 0
