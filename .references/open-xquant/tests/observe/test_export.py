"""Tests for oxq.observe.export — RunResult directory export."""

from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from oxq.core.types import BarSnapshot, Fill, Order, Portfolio, PositionSnapshot
from oxq.portfolio.analytics import RunResult


def _make_result() -> RunResult:
    """Minimal RunResult with all fields populated for export tests."""
    dates = pd.bdate_range("2024-01-01", periods=5)
    mktdata = {
        "AAPL": pd.DataFrame(
            {"open": [149, 150, 151, 152, 153], "close": [150, 151, 152, 153, 154]},
            index=dates,
        ),
        "GOOG": pd.DataFrame(
            {"open": [99, 100, 101, 102, 103], "close": [100, 101, 102, 103, 104]},
            index=dates,
        ),
    }
    trades = [
        Fill(
            order=Order(symbol="AAPL", side="BUY", shares=100),
            filled_price=Decimal("150.00"),
            filled_at="2024-01-02",
        ),
        Fill(
            order=Order(
                symbol="GOOG",
                side="BUY",
                shares=50,
                order_type="limit",
                limit_price=Decimal("100.50"),
            ),
            filled_price=Decimal("100.50"),
            filled_at="2024-01-03",
            fee=Decimal("9.95"),
        ),
    ]
    equity = [(d, 100_000.0 + i * 500.0) for i, d in enumerate(dates)]
    snapshots = [
        BarSnapshot(
            date=dates[0],
            target_weights={"AAPL": 0.6, "GOOG": 0.4},
            adjusted_weights={"AAPL": 0.55, "GOOG": 0.35},
            positions={
                "AAPL": PositionSnapshot(shares=100, avg_cost=150.0),
                "GOOG": PositionSnapshot(shares=50, avg_cost=100.0),
            },
            cash=45000.0,
            total_value=100000.0,
        ),
        BarSnapshot(
            date=dates[1],
            target_weights={"AAPL": 0.5, "GOOG": 0.5},
            adjusted_weights={"AAPL": 0.5, "GOOG": 0.5},
            positions={
                "AAPL": PositionSnapshot(shares=100, avg_cost=150.0),
                "GOOG": PositionSnapshot(shares=50, avg_cost=100.0),
            },
            cash=44500.0,
            total_value=100500.0,
        ),
    ]
    return RunResult(
        portfolio=Portfolio(cash=Decimal("44500")),
        trades=trades,
        equity_curve=equity,
        mktdata=mktdata,
        snapshots=snapshots,
    )


class TestFlattenEquity:
    def test_basic(self) -> None:
        from oxq.observe.export import _flatten_equity

        result = _make_result()
        df = _flatten_equity(result.equity_curve)
        assert list(df.columns) == ["value"]
        assert len(df) == 5
        assert df.iloc[0]["value"] == 100_000.0
        assert df.iloc[-1]["value"] == 102_000.0

    def test_empty(self) -> None:
        from oxq.observe.export import _flatten_equity

        df = _flatten_equity([])
        assert list(df.columns) == ["value"]
        assert len(df) == 0


class TestFlattenTrades:
    def test_basic(self) -> None:
        from oxq.observe.export import _flatten_trades

        result = _make_result()
        df = _flatten_trades(result.trades)
        assert len(df) == 2
        assert list(df.columns) == [
            "filled_at", "symbol", "side", "shares", "order_type",
            "limit_price", "stop_price", "filled_price", "fee",
        ]
        # First trade: market order, no limit/stop
        row0 = df.iloc[0]
        assert row0["symbol"] == "AAPL"
        assert row0["side"] == "BUY"
        assert row0["shares"] == 100
        assert row0["filled_price"] == 150.0
        assert row0["fee"] == 0.0
        assert pd.isna(row0["limit_price"])
        assert pd.isna(row0["stop_price"])
        # Second trade: limit order
        row1 = df.iloc[1]
        assert row1["symbol"] == "GOOG"
        assert row1["order_type"] == "limit"
        assert row1["limit_price"] == 100.50
        assert row1["fee"] == 9.95

    def test_empty(self) -> None:
        from oxq.observe.export import _flatten_trades

        df = _flatten_trades([])
        assert len(df) == 0
        assert "symbol" in df.columns


class TestFlattenSnapshots:
    def test_basic(self) -> None:
        from oxq.observe.export import _flatten_snapshots

        result = _make_result()
        df = _flatten_snapshots(result.snapshots)
        assert len(df) == 2
        # Fixed columns
        assert "cash" in df.columns
        assert "total_value" in df.columns
        # Dynamic columns for AAPL and GOOG
        assert "tw_AAPL" in df.columns
        assert "aw_AAPL" in df.columns
        assert "pos_AAPL_shares" in df.columns
        assert "pos_AAPL_avg_cost" in df.columns
        assert "tw_GOOG" in df.columns
        # Values from first snapshot
        row0 = df.iloc[0]
        assert row0["cash"] == 45000.0
        assert row0["total_value"] == 100000.0
        assert row0["tw_AAPL"] == 0.6
        assert row0["aw_AAPL"] == 0.55
        assert row0["pos_AAPL_shares"] == 100
        assert row0["pos_AAPL_avg_cost"] == 150.0

    def test_empty(self) -> None:
        from oxq.observe.export import _flatten_snapshots

        df = _flatten_snapshots([])
        assert len(df) == 0
        assert "cash" in df.columns
        assert "total_value" in df.columns


class TestSaveRunOutput:
    def _make_audit(self, result: RunResult) -> "AuditRecord":
        from oxq.observe.audit import AuditRecord
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        tracer.on_run_start("test_strat", {"signals": {}})
        tracer.on_run_end("ok")
        return AuditRecord.build(
            tracer=tracer,
            result=result,
            strategy_name="test_strat",
            strategy_config={"signals": {}},
            start_date="2024-01-01",
            end_date="2024-01-07",
            initial_cash=100_000.0,
        )

    def test_writes_all_files(self) -> None:
        from oxq.observe.export import save_run_output

        result = _make_result()
        audit = self._make_audit(result)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            save_run_output(out, result, audit)

            assert (out / "result.json").exists()
            assert (out / "snapshots.parquet").exists()
            assert (out / "trades.parquet").exists()
            assert (out / "equity_curve.parquet").exists()
            assert (out / "trace_spans.json").exists()
            assert (out / "mktdata" / "AAPL.parquet").exists()
            assert (out / "mktdata" / "GOOG.parquet").exists()

    def test_result_json_structure(self) -> None:
        from oxq.observe.export import save_run_output

        result = _make_result()
        audit = self._make_audit(result)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            save_run_output(out, result, audit)

            data = json.loads((out / "result.json").read_text())
            # metrics present
            assert "metrics" in data
            m = data["metrics"]
            assert "total_return" in m
            assert "sharpe_ratio" in m
            assert "max_drawdown" in m
            assert "annualized_return" in m
            # audit_record present and recoverable
            assert "audit_record" in data
            from oxq.observe.audit import AuditRecord
            recovered = AuditRecord.from_dict(data["audit_record"])
            assert recovered.run_id == audit.run_id

    def test_parquet_roundtrip(self) -> None:
        from oxq.observe.export import save_run_output

        result = _make_result()
        audit = self._make_audit(result)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            save_run_output(out, result, audit)

            eq = pd.read_parquet(out / "equity_curve.parquet")
            assert len(eq) == 5
            tr = pd.read_parquet(out / "trades.parquet")
            assert len(tr) == 2
            sn = pd.read_parquet(out / "snapshots.parquet")
            assert len(sn) == 2
            aapl = pd.read_parquet(out / "mktdata" / "AAPL.parquet")
            assert len(aapl) == 5

    def test_trace_spans_json(self) -> None:
        from oxq.observe.export import save_run_output

        result = _make_result()
        audit = self._make_audit(result)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            save_run_output(out, result, audit)

            spans = json.loads((out / "trace_spans.json").read_text())
            assert isinstance(spans, list)
            for span in spans:
                assert "trace_id" in span
                assert "component" in span

    def test_mktdata_hash_matches_audit(self) -> None:
        from oxq.observe.export import save_run_output
        from oxq.observe.hashing import hash_mktdata

        result = _make_result()
        audit = self._make_audit(result)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            save_run_output(out, result, audit)

            reloaded = {
                p.stem: pd.read_parquet(p)
                for p in (out / "mktdata").glob("*.parquet")
            }
            assert hash_mktdata(reloaded) == audit.mktdata_hash

    def test_empty_result(self) -> None:
        from oxq.observe.export import save_run_output

        empty_result = RunResult(
            portfolio=Portfolio(cash=Decimal("100000")),
            trades=[],
            equity_curve=[],
            mktdata={},
            snapshots=[],
        )
        audit = self._make_audit(empty_result)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            save_run_output(out, result=empty_result, audit=audit)

            assert (out / "result.json").exists()
            assert (out / "mktdata").is_dir()
            eq = pd.read_parquet(out / "equity_curve.parquet")
            assert len(eq) == 0

    def test_metric_failure_writes_null(self) -> None:
        from oxq.observe.export import save_run_output

        one_point = RunResult(
            portfolio=Portfolio(cash=Decimal("100000")),
            trades=[],
            equity_curve=[("2024-01-01", 100_000.0)],
            mktdata={},
            snapshots=[],
        )
        audit = self._make_audit(one_point)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            save_run_output(out, result=one_point, audit=audit)

            data = json.loads((out / "result.json").read_text())
            assert data["metrics"]["total_return"] == 0.0


class TestPublicImport:
    def test_import_from_observe(self) -> None:
        from oxq.observe import save_run_output  # noqa: F401

        assert callable(save_run_output)
