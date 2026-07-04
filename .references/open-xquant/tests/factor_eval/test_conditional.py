"""Tests for market state conditional analysis."""

from __future__ import annotations

import pandas as pd
import pytest

from oxq.factor_eval.conditional import compute_conditional_analysis


class TestComputeConditionalAnalysis:

    @pytest.fixture()
    def data(self) -> dict:
        """12-point dataset with 3 market states.

        States: trend(4), ranging(4), crash(4)
        factor:  [0.5, 0.8, 0.3, 0.6,  0.2, -0.1, 0.4, -0.3,  -0.5, -0.8, 0.1, -0.2]
        returns: [0.03, 0.04, 0.02, 0.05,  0.01, -0.01, 0.02, -0.02,  -0.05, -0.03, -0.01, -0.04]
        states:  [trend*4, ranging*4, crash*4]

        Trend: all long, all positive → hit rate 4/4=1.0
        Ranging: long[0.2,0.4]→ret[0.01,0.02]→2hits; short[-0.1,-0.3]→ret[-0.01,-0.02]→2hits → 4/4=1.0
        Crash: long[0.1]→ret[-0.01]→0hits; short[-0.5,-0.8,-0.2]→ret[-0.05,-0.03,-0.04]→3hits → 3/4=0.75
        """
        dates = pd.date_range("2024-01-01", periods=12, freq="B")
        factor_values = pd.Series(
            [0.5, 0.8, 0.3, 0.6, 0.2, -0.1, 0.4, -0.3, -0.5, -0.8, 0.1, -0.2],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 12], names=["date", "asset"],
            ),
        )
        forward_returns = pd.DataFrame(
            {"a": [0.03, 0.04, 0.02, 0.05, 0.01, -0.01, 0.02, -0.02, -0.05, -0.03, -0.01, -0.04]},
            index=dates,
        )
        market_state = pd.Series(
            ["trend"] * 4 + ["ranging"] * 4 + ["crash"] * 4,
            index=dates,
        )
        return {
            "factor_values": factor_values,
            "forward_returns": forward_returns,
            "market_state": market_state,
        }

    def test_returns_all_states(self, data: dict) -> None:
        result = compute_conditional_analysis(**data)
        assert set(result["by_state"].keys()) == {"trend", "ranging", "crash"}

    def test_trend_hit_rate(self, data: dict) -> None:
        result = compute_conditional_analysis(**data)
        assert result["by_state"]["trend"]["hit_rate"] == pytest.approx(1.0)

    def test_crash_hit_rate(self, data: dict) -> None:
        result = compute_conditional_analysis(**data)
        assert result["by_state"]["crash"]["hit_rate"] == pytest.approx(0.75)

    def test_sample_counts(self, data: dict) -> None:
        result = compute_conditional_analysis(**data)
        assert result["by_state"]["trend"]["sample_count"] == 4
        assert result["by_state"]["ranging"]["sample_count"] == 4
        assert result["by_state"]["crash"]["sample_count"] == 4

    def test_small_sample_warning(self) -> None:
        dates = pd.date_range("2024-01-01", periods=6, freq="B")
        fv = pd.Series(
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 6], names=["date", "asset"],
            ),
        )
        fr = pd.DataFrame({"a": [0.01, 0.02, 0.03, 0.01, 0.02, 0.03]}, index=dates)
        ms = pd.Series(["trend"] * 3 + ["crash"] * 3, index=dates)
        result = compute_conditional_analysis(fv, fr, ms)
        assert result["by_state"]["trend"]["warning"] is not None

    def test_none_market_state_returns_empty(self) -> None:
        dates = pd.date_range("2024-01-01", periods=5, freq="B")
        fv = pd.Series(
            [0.1, 0.2, 0.3, 0.4, 0.5],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 5], names=["date", "asset"],
            ),
        )
        fr = pd.DataFrame({"a": [0.01, 0.02, 0.03, 0.01, 0.02]}, index=dates)
        result = compute_conditional_analysis(fv, fr, market_state=None)
        assert result["by_state"] == {}
        assert result["skipped"] is True

    def test_avg_return_per_state(self, data: dict) -> None:
        result = compute_conditional_analysis(**data)
        assert result["by_state"]["trend"]["avg_return"] == pytest.approx(0.035)
