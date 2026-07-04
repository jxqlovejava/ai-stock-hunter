"""Observe layer — strategy diagnostics, tracing, and audit."""

__all__ = [
    "AuditRecord",
    "BadPeriod",
    "DefaultTracer",
    "Experiment",
    "ExperimentLog",
    "MarketStateDetector",
    "StrategyMonitor",
    "TraceSpan",
    "save_run_output",
]

_IMPORTS = {
    "AuditRecord": "oxq.observe.audit",
    "BadPeriod": "oxq.observe.monitor",
    "DefaultTracer": "oxq.observe.tracer",
    "Experiment": "oxq.observe.experiment",
    "ExperimentLog": "oxq.observe.experiment",
    "MarketStateDetector": "oxq.observe.detector",
    "StrategyMonitor": "oxq.observe.monitor",
    "TraceSpan": "oxq.observe.tracer",
    "save_run_output": "oxq.observe.export",
}


def __getattr__(name: str):
    if name in _IMPORTS:
        import importlib

        module = importlib.import_module(_IMPORTS[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
