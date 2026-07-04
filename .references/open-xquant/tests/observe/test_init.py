"""Tests for oxq.observe package exports."""


def test_public_imports() -> None:
    from oxq.observe import (
        BadPeriod,
        Experiment,
        ExperimentLog,
        MarketStateDetector,
        StrategyMonitor,
    )
    assert StrategyMonitor is not None
    assert MarketStateDetector is not None
    assert ExperimentLog is not None
    assert BadPeriod is not None
    assert Experiment is not None
