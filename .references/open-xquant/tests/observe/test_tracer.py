"""Tests for Tracer — component-level execution tracing."""

from __future__ import annotations

import pytest


class TestObserveExports:
    def test_tracer_exports(self) -> None:
        from oxq.observe import DefaultTracer, TraceSpan
        assert DefaultTracer is not None
        assert TraceSpan is not None

    def test_audit_exports(self) -> None:
        from oxq.observe import AuditRecord
        assert AuditRecord is not None


class TestTraceSpan:
    def test_frozen(self) -> None:
        from oxq.observe.tracer import TraceSpan

        span = TraceSpan(
            trace_id="t1",
            span_id="s1",
            parent_id=None,
            component="indicator:sma_fast",
            inputs={"column": "close", "period": 10},
            output_summary={"rows": 252, "non_null": 243},
            started_at="2026-01-01T00:00:00",
            ended_at="2026-01-01T00:00:01",
            duration_ms=1000.0,
            status="ok",
            error=None,
        )
        assert span.component == "indicator:sma_fast"
        assert span.status == "ok"
        with pytest.raises(AttributeError):
            span.status = "error"

    def test_error_span(self) -> None:
        from oxq.observe.tracer import TraceSpan

        span = TraceSpan(
            trace_id="t1",
            span_id="s2",
            parent_id="s1",
            component="indicator:broken",
            inputs={},
            output_summary={},
            started_at="2026-01-01T00:00:00",
            ended_at="2026-01-01T00:00:01",
            duration_ms=500.0,
            status="error",
            error="KeyError: 'missing_col'",
        )
        assert span.status == "error"
        assert "missing_col" in span.error


class TestDefaultTracer:
    def test_on_run_start_returns_trace_id(self) -> None:
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        trace_id = tracer.on_run_start("sma_crossover", {"indicators": {}})
        assert isinstance(trace_id, str)
        assert len(trace_id) > 0

    def test_collect_indicator_span(self) -> None:
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        tracer.on_run_start("test", {})
        tracer.on_indicator(
            name="sma_fast",
            params={"column": "close", "period": 10},
            output_summary={"rows": 252, "non_null": 243},
            duration_ms=2.1,
        )
        assert len(tracer.spans) == 1
        assert tracer.spans[0].component == "indicator:sma_fast"
        assert tracer.spans[0].status == "ok"
        assert tracer.spans[0].duration_ms == 2.1

    def test_collect_signal_span(self) -> None:
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        tracer.on_run_start("test", {})
        tracer.on_signal(
            name="golden_cross",
            inputs={"fast": "sma_fast", "slow": "sma_slow"},
            output_summary={"signal_count": 5},
            duration_ms=1.0,
        )
        assert len(tracer.spans) == 1
        assert tracer.spans[0].component == "signal:golden_cross"

    def test_collect_rule_span(self) -> None:
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        tracer.on_run_start("test", {})
        tracer.on_rule(
            name="enter_long",
            rule_type="entry",
            output_summary={"orders_generated": 3},
            duration_ms=5.0,
        )
        assert len(tracer.spans) == 1
        assert tracer.spans[0].component == "rule:enter_long"

    def test_on_run_end_records_status(self) -> None:
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        tracer.on_run_start("test", {})
        tracer.on_run_end("ok")
        assert tracer.run_status == "ok"

    def test_full_trace_sequence(self) -> None:
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        tracer.on_run_start("strat", {"indicators": {"sma_fast": {}}})
        tracer.on_indicator("sma_fast", {"period": 10}, {"rows": 100}, 1.0)
        tracer.on_indicator("sma_slow", {"period": 50}, {"rows": 100}, 2.0)
        tracer.on_signal("golden_cross", {"fast": "sma_fast"}, {"signal_count": 3}, 0.5)
        tracer.on_rule("enter", "entry", {"orders_generated": 2}, 3.0)
        tracer.on_rule("exit", "exit", {"orders_generated": 1}, 2.0)
        tracer.on_run_end("ok")
        assert len(tracer.spans) == 5
        ids = {s.trace_id for s in tracer.spans}
        assert len(ids) == 1

    def test_error_indicator(self) -> None:
        from oxq.observe.tracer import DefaultTracer

        tracer = DefaultTracer()
        tracer.on_run_start("test", {})
        tracer.on_indicator(
            name="broken",
            params={},
            output_summary={},
            duration_ms=0.5,
            status="error",
            error="KeyError: 'missing'",
        )
        assert tracer.spans[0].status == "error"
        assert tracer.spans[0].error == "KeyError: 'missing'"
