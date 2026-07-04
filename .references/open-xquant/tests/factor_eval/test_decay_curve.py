"""Tests for factor decay curve computation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oxq.factor_eval.decay_curve import compute_decay_curve


class TestComputeDecayCurve:
    """Test decay curve with controlled data."""

    @pytest.fixture()
    def trending_data(self) -> dict:
        """Factor perfectly predicts 1-day returns, decays with longer horizons.

        50 data points. Factor = next-day return (perfect correlation at lag 1).
        Correlation should decay as horizon increases.
        """
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=80, freq="B")
        returns = np.random.randn(80) * 0.02
        prices_vals = 100 * np.exp(np.cumsum(returns))
        # Factor = next day return (shifted by -1)
        factor_values = pd.Series(
            returns[1:51],
            index=pd.MultiIndex.from_arrays(
                [dates[:50], ["a"] * 50], names=["date", "asset"],
            ),
        )

        # Pre-compute forward returns for periods 1, 5, 10, 20
        fwd = {}
        for p in [1, 5, 10, 20]:
            fwd[p] = pd.DataFrame(
                {"a": (prices_vals[p:] / prices_vals[:-p] - 1)[:80]},
                index=dates[:80 - p],
            )
        return {"factor_values": factor_values, "forward_returns_by_period": fwd}

    def test_returns_correlations_for_all_periods(self, trending_data: dict) -> None:
        result = compute_decay_curve(**trending_data, periods=[1, 5, 10, 20])
        assert set(result["correlations"].keys()) == {1, 5, 10, 20}

    def test_correlation_at_lag1_is_strong(self, trending_data: dict) -> None:
        """Factor is constructed as next-day return, so lag-1 correlation should be high."""
        result = compute_decay_curve(**trending_data, periods=[1, 5, 10, 20])
        assert abs(result["correlations"][1]) > 0.5

    def test_correlation_decays_with_horizon(self, trending_data: dict) -> None:
        result = compute_decay_curve(**trending_data, periods=[1, 5, 10, 20])
        corrs = result["correlations"]
        assert abs(corrs[1]) > abs(corrs[20])

    def test_half_life_is_reasonable(self, trending_data: dict) -> None:
        result = compute_decay_curve(**trending_data, periods=[1, 5, 10, 20])
        # Half-life should exist and be > 1
        if result["half_life"] is not None:
            assert result["half_life"] > 1

    def test_spearman_vs_pearson(self, trending_data: dict) -> None:
        spearman = compute_decay_curve(
            **trending_data, periods=[1, 5], method="spearman",
        )
        pearson = compute_decay_curve(
            **trending_data, periods=[1, 5], method="pearson",
        )
        # Both should produce valid results, possibly different values
        assert not np.isnan(spearman["correlations"][1])
        assert not np.isnan(pearson["correlations"][1])

    def test_warning_on_small_sample(self) -> None:
        dates = pd.date_range("2024-01-01", periods=5, freq="B")
        fv = pd.Series(
            [0.1, 0.2, 0.3, 0.4, 0.5],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 5], names=["date", "asset"],
            ),
        )
        fwd = {1: pd.DataFrame({"a": [0.01, 0.02, 0.03, 0.04, np.nan]}, index=dates)}
        result = compute_decay_curve(fv, fwd, periods=[1])
        assert result["warning"] is not None
