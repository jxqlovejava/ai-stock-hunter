"""Tests for lookahead bias detection."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oxq.factor_eval.bias import detect_lookahead_bias


class TestDetectLookaheadBias:

    def test_perfect_correlation_triggers_warning(self) -> None:
        """Factor = current-period return -> correlation ~ 1.0 -> warning."""
        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        prices = pd.DataFrame(
            {"a": 100 * np.exp(np.cumsum(np.random.RandomState(42).randn(50) * 0.02))},
            index=dates,
        )
        # Factor = same-day return (lookahead!)
        daily_ret = prices["a"].pct_change().dropna()
        factor_values = pd.Series(
            daily_ret.values,
            index=pd.MultiIndex.from_arrays(
                [daily_ret.index, ["a"] * len(daily_ret)], names=["date", "asset"],
            ),
        )
        result = detect_lookahead_bias(factor_values, prices)
        assert result["has_warning"] is True
        assert abs(result["correlation"]) > 0.5

    def test_no_warning_for_unrelated_factor(self) -> None:
        """Random factor should not trigger warning."""
        np.random.seed(123)
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        prices = pd.DataFrame(
            {"a": 100 + np.cumsum(np.random.randn(100))},
            index=dates,
        )
        factor_values = pd.Series(
            np.random.randn(100),
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 100], names=["date", "asset"],
            ),
        )
        result = detect_lookahead_bias(factor_values, prices)
        assert result["has_warning"] is False

    def test_custom_threshold(self) -> None:
        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        prices = pd.DataFrame(
            {"a": 100 * np.exp(np.cumsum(np.random.RandomState(42).randn(50) * 0.02))},
            index=dates,
        )
        daily_ret = prices["a"].pct_change().dropna()
        factor_values = pd.Series(
            daily_ret.values,
            index=pd.MultiIndex.from_arrays(
                [daily_ret.index, ["a"] * len(daily_ret)], names=["date", "asset"],
            ),
        )
        # With very high threshold, even perfect correlation won't trigger
        result = detect_lookahead_bias(factor_values, prices, threshold=0.99)
        # correlation is ~1.0, threshold 0.99 -- still triggers
        assert result["has_warning"] is True

    def test_returns_message_when_warning(self) -> None:
        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        prices = pd.DataFrame(
            {"a": 100 * np.exp(np.cumsum(np.random.RandomState(42).randn(50) * 0.02))},
            index=dates,
        )
        daily_ret = prices["a"].pct_change().dropna()
        factor_values = pd.Series(
            daily_ret.values,
            index=pd.MultiIndex.from_arrays(
                [daily_ret.index, ["a"] * len(daily_ret)], names=["date", "asset"],
            ),
        )
        result = detect_lookahead_bias(factor_values, prices)
        assert result["message"] is not None
        assert "lookahead" in result["message"].lower() or "前视" in result["message"]
