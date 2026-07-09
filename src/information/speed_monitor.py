"""Information speed monitor — measure latency from data arrival to signal generation.

Passive observer: records timestamps at each pipeline stage without blocking.
Answers: "Is our information processing fast enough to create alpha?"
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SpeedMetrics:
    avg_latency_seconds: float = 0.0
    time_to_first_signal: float = 0.0  # Seconds from event detection to first signal
    event_types_tracked: dict[str, int] = field(default_factory=dict)
    fastest_source: str = "unknown"
    alpha_correlation: float = 0.0  # Speed-to-accuracy correlation (future)
    bottlenecks: list[str] = field(default_factory=list)
    total_events: int = 0
    updated_at: datetime = field(default_factory=datetime.now)


class SpeedMonitor:
    """Passive latency tracker for the information→signal pipeline.

    Usage (from orchestrator or aggregator):
        monitor = SpeedMonitor()
        t0 = time.time()
        # ... do work ...
        monitor.record_latency("guosen", "quote_fetch", (time.time()-t0)*1000)
    """

    def __init__(self):
        self._records: list[dict] = []
        self._benchmarks: dict[str, list[float]] = defaultdict(list)
        self._max_records = 1000  # Prevent unbounded growth
        self._lock = threading.Lock()  # Thread safety for concurrent access

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_latency(self, source: str, stage: str, elapsed_ms: float) -> None:
        """Record a latency measurement for a source+stage pair (thread-safe)."""
        with self._lock:
            self._records.append({
                "source": source,
                "stage": stage,
                "elapsed_ms": elapsed_ms,
                "timestamp": datetime.now(),
            })
            # Track per-source benchmarks
            self._benchmarks[f"{source}:{stage}"].append(elapsed_ms)

            # Prune old records
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records // 2 :]

    def time_event(self, event_type: str) -> float:
        """Start timing an event. Returns start timestamp."""
        return time.time()

    def end_event(self, event_type: str, start_ts: float, source: str = "unknown") -> float:
        """End timing an event, record latency. Returns elapsed_ms."""
        elapsed_ms = (time.time() - start_ts) * 1000
        self.record_latency(source, event_type, elapsed_ms)
        return elapsed_ms

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> SpeedMetrics:
        """Compute aggregate speed metrics from recorded data (thread-safe)."""
        with self._lock:
            records_snapshot = list(self._records)

        metrics = SpeedMetrics(total_events=len(records_snapshot))

        if not records_snapshot:
            return metrics

        # Average latency
        total_ms = sum(r["elapsed_ms"] for r in records_snapshot)
        metrics.avg_latency_seconds = total_ms / len(records_snapshot) / 1000.0

        # Event type tracking
        for r in records_snapshot:
            stage = r["stage"]
            metrics.event_types_tracked[stage] = metrics.event_types_tracked.get(stage, 0) + 1

        # Fastest source
        source_avgs: dict[str, list[float]] = defaultdict(list)
        for r in records_snapshot:
            source_avgs[r["source"]].append(r["elapsed_ms"])
        if source_avgs:
            avg_by_source = {s: sum(v) / len(v) for s, v in source_avgs.items()}
            metrics.fastest_source = min(avg_by_source, key=avg_by_source.get)  # type: ignore[arg-type]

        # Bottlenecks: stages with avg latency > 2x overall average
        overall_avg = total_ms / len(records_snapshot)
        stage_avgs: dict[str, list[float]] = defaultdict(list)
        for r in records_snapshot:
            stage_avgs[r["stage"]].append(r["elapsed_ms"])
        for stage, latencies in stage_avgs.items():
            stage_avg = sum(latencies) / len(latencies)
            if stage_avg > overall_avg * 2.0:
                metrics.bottlenecks.append(f"{stage} ({stage_avg:.0f}ms)")

        return metrics

    # ------------------------------------------------------------------
    # Benchmarking
    # ------------------------------------------------------------------

    def benchmark_source_speed(self, sources: Optional[list[str]] = None) -> dict[str, float]:
        """Compare average latencies across sources. Returns {source: avg_ms}."""
        result: dict[str, float] = {}
        for key, latencies in self._benchmarks.items():
            if sources and not any(s in key for s in sources):
                continue
            result[key] = sum(latencies) / len(latencies)
        return result

    def get_source_comparison(self) -> dict:
        """Human-readable source speed comparison for CLI output."""
        avgs = self.benchmark_source_speed()
        if not avgs:
            return {"status": "no_data", "message": "No latency data recorded yet"}

        sorted_avgs = sorted(avgs.items(), key=lambda x: x[1])
        return {
            "rankings": [{"key": k, "avg_ms": round(v, 1)} for k, v in sorted_avgs],
            "fastest": sorted_avgs[0][0] if sorted_avgs else "unknown",
            "slowest": sorted_avgs[-1][0] if sorted_avgs else "unknown",
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all recorded data."""
        self._records.clear()
        self._benchmarks.clear()

    def __len__(self) -> int:
        return len(self._records)
