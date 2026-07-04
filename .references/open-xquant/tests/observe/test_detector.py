"""Tests for MarketStateDetector — market state classification."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Portfolio
from oxq.portfolio.analytics import RunResult


def _make_result_with_mktdata(
    symbols: list[str],
    n_days: int = 200,
    volatility: float = 0.02,
    seed: int = 42,
) -> RunResult:
    """Build RunResult with synthetic market data."""
    np.random.seed(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_days)
    mktdata = {}
    for sym in symbols:
        returns = np.random.normal(0.0005, volatility, n_days)
        close = 100 * np.cumprod(1 + returns)
        mktdata[sym] = pd.DataFrame({"close": close}, index=dates)

    values = np.linspace(100, 120, n_days).tolist()
    return RunResult(
        portfolio=Portfolio(cash=Decimal("120")),
        trades=[],
        equity_curve=[(d, v) for d, v in zip(dates, values)],
        mktdata=mktdata,
    )


class TestMarketVol:
    def test_length(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A", "B"], n_days=100)
        detector = MarketStateDetector(result, vol_lookback=20)
        assert len(detector.market_vol) == 100

    def test_annualized(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A"], n_days=100, volatility=0.01)
        detector = MarketStateDetector(result, vol_lookback=20)
        valid = detector.market_vol.dropna()
        assert valid.median() == pytest.approx(0.01 * np.sqrt(252), rel=0.3)


class TestStates:
    def test_three_states(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A", "B"], n_days=200)
        detector = MarketStateDetector(result, vol_lookback=20)
        valid_states = detector.states.dropna()
        assert set(valid_states.unique()).issubset({"high", "normal", "low"})

    def test_masks_consistent_with_states(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A", "B"], n_days=200)
        detector = MarketStateDetector(result, vol_lookback=20)
        valid = detector.states.dropna().index
        high_from_mask = detector.high_vol_mask.reindex(valid).fillna(False)
        high_from_states = detector.states.reindex(valid) == "high"
        pd.testing.assert_series_equal(high_from_mask, high_from_states, check_names=False)


class TestThresholds:
    def test_thresholds(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A"], n_days=200)
        detector = MarketStateDetector(
            result, vol_lookback=20,
            high_vol_multiplier=1.3, low_vol_multiplier=0.7,
        )
        assert detector.high_vol_line == pytest.approx(detector.vol_median * 1.3, rel=1e-6)
        assert detector.low_vol_line == pytest.approx(detector.vol_median * 0.7, rel=1e-6)


class TestSymbolsParam:
    def test_default_uses_all_symbols(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A", "B", "C"], n_days=100)
        detector = MarketStateDetector(result, vol_lookback=20)
        assert len(detector.market_vol) == 100

    def test_subset_symbols(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A", "B", "C"], n_days=100)
        detector = MarketStateDetector(result, symbols=("A",), vol_lookback=20)
        assert len(detector.market_vol) == 100


    def test_invalid_symbol_raises(self) -> None:
        """Passing a symbol not in mktdata should raise KeyError."""
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A", "B"], n_days=100)
        with pytest.raises(KeyError):
            MarketStateDetector(result, symbols=("NONEXISTENT",), vol_lookback=20)


class TestPerformanceByState:
    def test_returns_all_states(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A", "B"], n_days=200)
        detector = MarketStateDetector(result, vol_lookback=20)
        perf = detector.performance_by_state(result)
        assert isinstance(perf, dict)
        assert "normal" in perf

    def test_result_structure(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A", "B"], n_days=200)
        detector = MarketStateDetector(result, vol_lookback=20)
        perf = detector.performance_by_state(result)
        for state, metrics in perf.items():
            assert "days" in metrics
            assert "ann_return" in metrics
            assert "sharpe" in metrics

    def test_days_sum_to_total(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result = _make_result_with_mktdata(["A", "B"], n_days=200)
        detector = MarketStateDetector(result, vol_lookback=20)
        perf = detector.performance_by_state(result)
        total_days = sum(m["days"] for m in perf.values())
        valid_states = detector.states.dropna()
        assert total_days == len(valid_states)

    def test_performance_by_state_warns_on_low_overlap(self) -> None:
        """Warn when date overlap is less than 50%."""
        import warnings

        from oxq.observe.detector import MarketStateDetector

        result1 = _make_result_with_mktdata(["A", "B"], n_days=200, seed=42)
        # Create result2 with completely different dates
        np.random.seed(99)
        dates2 = pd.bdate_range("2025-01-01", periods=200)
        values2 = np.linspace(100, 120, 200).tolist()
        result2 = RunResult(
            portfolio=Portfolio(cash=Decimal("120")),
            trades=[],
            equity_curve=[(d, v) for d, v in zip(dates2, values2)],
            mktdata={},
        )
        detector = MarketStateDetector(result1, vol_lookback=20)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            detector.performance_by_state(result2)
            assert len(w) == 1
            assert "overlap" in str(w[0].message).lower()

    def test_no_overlap_returns_empty(self) -> None:
        """Result with no overlapping dates returns empty performance."""
        import warnings

        from oxq.observe.detector import MarketStateDetector
        result1 = _make_result_with_mktdata(["A"], n_days=100, seed=42)
        # Create result2 with completely different dates
        dates2 = pd.bdate_range("2026-01-01", periods=50)
        values2 = np.linspace(100, 120, 50).tolist()
        result2 = RunResult(
            portfolio=Portfolio(cash=Decimal("120")),
            trades=[],
            equity_curve=[(d, v) for d, v in zip(dates2, values2)],
            mktdata={},
        )
        detector = MarketStateDetector(result1, vol_lookback=20)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            perf = detector.performance_by_state(result2)
        # No overlapping dates -> empty or all states have 0 days
        total_days = sum(m["days"] for m in perf.values())
        assert total_days == 0

    def test_different_result(self) -> None:
        from oxq.observe.detector import MarketStateDetector
        result1 = _make_result_with_mktdata(["A", "B"], n_days=200, seed=42)
        result2 = _make_result_with_mktdata(["A", "B"], n_days=200, seed=99)
        detector = MarketStateDetector(result1, vol_lookback=20)
        perf = detector.performance_by_state(result2)
        assert isinstance(perf, dict)
