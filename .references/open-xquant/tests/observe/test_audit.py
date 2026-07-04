"""Tests for AuditRecord — run snapshot with layered hashes."""

from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from oxq.core.types import Fill, Order, Portfolio
from oxq.portfolio.analytics import RunResult


def _make_result() -> RunResult:
    dates = pd.bdate_range("2024-01-01", periods=5)
    mktdata = {
        "AAPL": pd.DataFrame(
            {"close": [150.0, 151.0, 152.0, 153.0, 154.0]},
            index=dates,
        ),
    }
    trades = [
        Fill(
            order=Order(symbol="AAPL", side="BUY", shares=100),
            filled_price=Decimal("150.00"),
            filled_at="2024-01-02",
        ),
    ]
    equity = [(d, 100000.0 + i * 500.0) for i, d in enumerate(dates)]
    return RunResult(
        portfolio=Portfolio(cash=Decimal("50000")),
        trades=trades,
        equity_curve=equity,
        mktdata=mktdata,
    )


class TestAuditRecordBuild:
    def test_from_tracer_and_result(self) -> None:
        from oxq.observe.audit import AuditRecord
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        tracer.on_run_start("sma_cross", {"indicators": {"sma_fast": {"period": 10}}})
        tracer.on_indicator("sma_fast", {"period": 10}, {"rows": 5}, 1.0)
        tracer.on_run_end("ok")

        result = _make_result()
        audit = AuditRecord.build(
            tracer=tracer,
            result=result,
            strategy_name="sma_cross",
            strategy_config={"indicators": {"sma_fast": {"period": 10}}},
            start_date="2024-01-01",
            end_date="2024-01-07",
            initial_cash=100000.0,
        )
        assert audit.strategy_name == "sma_cross"
        assert audit.run_id.startswith("run_")
        assert len(audit.trace_spans) == 1
        assert audit.mktdata_hash.startswith("sha256:")
        assert audit.trades_hash.startswith("sha256:")
        assert audit.equity_hash.startswith("sha256:")
        assert audit.result_hash.startswith("sha256:")

    def test_frozen(self) -> None:
        from oxq.observe.audit import AuditRecord
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        tracer.on_run_start("test", {})
        tracer.on_run_end("ok")
        result = _make_result()
        audit = AuditRecord.build(
            tracer=tracer,
            result=result,
            strategy_name="test",
            strategy_config={},
            start_date="2024-01-01",
            end_date="2024-01-07",
            initial_cash=100000.0,
        )
        with pytest.raises(AttributeError):
            audit.run_id = "changed"


class TestAuditRecordSerialize:
    def _build_audit(self):
        from oxq.observe.audit import AuditRecord
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        tracer.on_run_start("test", {})
        tracer.on_indicator("sma", {"period": 10}, {"rows": 5}, 1.0)
        tracer.on_run_end("ok")
        result = _make_result()
        return AuditRecord.build(
            tracer=tracer,
            result=result,
            strategy_name="test",
            strategy_config={"ind": {}},
            start_date="2024-01-01",
            end_date="2024-01-07",
            initial_cash=100000.0,
        )

    def test_to_dict_roundtrip(self) -> None:
        from oxq.observe.audit import AuditRecord

        audit = self._build_audit()
        d = audit.to_dict()
        restored = AuditRecord.from_dict(d)
        assert restored.run_id == audit.run_id
        assert restored.result_hash == audit.result_hash
        assert len(restored.trace_spans) == len(audit.trace_spans)

    def test_to_json_file(self) -> None:
        from oxq.observe.audit import AuditRecord

        audit = self._build_audit()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.json"
            audit.to_json(str(path))
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["run_id"] == audit.run_id

    def test_from_json_file(self) -> None:
        from oxq.observe.audit import AuditRecord

        audit = self._build_audit()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.json"
            audit.to_json(str(path))
            restored = AuditRecord.from_json(str(path))
            assert restored.run_id == audit.run_id
            assert restored.result_hash == audit.result_hash

    def test_deterministic_hashes(self) -> None:
        """Same result should produce same hashes."""
        from oxq.observe.audit import AuditRecord
        from oxq.observe.tracer import DefaultTracer

        result = _make_result()

        def build():
            tracer = DefaultTracer()
            tracer.on_run_start("test", {})
            tracer.on_run_end("ok")
            return AuditRecord.build(
                tracer=tracer,
                result=result,
                strategy_name="test",
                strategy_config={},
                start_date="2024-01-01",
                end_date="2024-01-07",
                initial_cash=100000.0,
            )

        a1 = build()
        a2 = build()
        assert a1.mktdata_hash == a2.mktdata_hash
        assert a1.trades_hash == a2.trades_hash
        assert a1.equity_hash == a2.equity_hash
        assert a1.result_hash == a2.result_hash
