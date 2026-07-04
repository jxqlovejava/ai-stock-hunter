"""Tests for information speed monitor."""

import time
import pytest
from src.information.speed_monitor import SpeedMonitor, SpeedMetrics


class TestSpeedMetrics:
    def test_default_construction(self):
        m = SpeedMetrics()
        assert m.avg_latency_seconds == 0.0
        assert m.total_events == 0
        assert m.fastest_source == "unknown"


class TestSpeedMonitor:
    def setup_method(self):
        self.monitor = SpeedMonitor()

    def test_record_latency(self):
        self.monitor.record_latency("guosen", "quote_fetch", 150.0)
        assert len(self.monitor) == 1

    def test_record_multiple_sources(self):
        self.monitor.record_latency("guosen", "quote_fetch", 100.0)
        self.monitor.record_latency("akshare", "quote_fetch", 300.0)
        self.monitor.record_latency("guosen", "northbound", 200.0)
        assert len(self.monitor) == 3

    def test_get_metrics_no_data(self):
        metrics = self.monitor.get_metrics()
        assert metrics.total_events == 0
        assert metrics.avg_latency_seconds == 0.0

    def test_get_metrics_with_data(self):
        self.monitor.record_latency("guosen", "quote_fetch", 100.0)
        self.monitor.record_latency("guosen", "quote_fetch", 200.0)
        metrics = self.monitor.get_metrics()
        assert metrics.total_events == 2
        assert metrics.avg_latency_seconds == 0.15  # (100+200)/2 = 150ms

    def test_fastest_source(self):
        self.monitor.record_latency("guosen", "quote", 100.0)
        self.monitor.record_latency("akshare", "quote", 300.0)
        self.monitor.record_latency("huatai", "quote", 500.0)
        metrics = self.monitor.get_metrics()
        assert metrics.fastest_source == "guosen"

    def test_time_event(self):
        start = self.monitor.time_event("test_event")
        time.sleep(0.01)
        elapsed = self.monitor.end_event("test_event", start, "test_source")
        assert elapsed > 0
        assert len(self.monitor) == 1

    def test_get_source_comparison_no_data(self):
        result = self.monitor.get_source_comparison()
        assert result["status"] == "no_data"

    def test_benchmark_source_speed(self):
        self.monitor.record_latency("guosen", "query", 100.0)
        self.monitor.record_latency("akshare", "query", 200.0)
        bench = self.monitor.benchmark_source_speed(["guosen", "akshare"])
        assert "guosen:query" in bench or len(bench) > 0

    def test_reset(self):
        self.monitor.record_latency("test", "stage", 1.0)
        self.monitor.reset()
        assert len(self.monitor) == 0
