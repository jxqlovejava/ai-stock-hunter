"""Tests for hit rate computation."""

from __future__ import annotations

import pandas as pd
import pytest

from oxq.factor_eval.hit_rate import compute_hit_rate


class TestComputeHitRate:
    """Test hit rate with hand-calculated values."""

    @pytest.fixture()
    def data(self) -> dict:
        """10-point factor + return series for one asset.

        factor:  [0.5, -0.3, 0.8, -0.1, 0.6, -0.4, 0.2, 0.9, -0.5, 0.3]
        returns: [0.02, -0.01, 0.03, 0.01, -0.02, -0.03, 0.01, 0.04, -0.02, 0.01]

        Long signals (factor > 0): indices 0,2,4,6,7,9 → returns: 0.02, 0.03, -0.02, 0.01, 0.04, 0.01
          hits (return > 0): 0,2,6,7,9 → 5 out of 6 → 83.33%
        Short signals (factor < 0): indices 1,3,5,8 → returns: -0.01, 0.01, -0.03, -0.02
          hits (return < 0): 1,5,8 → 3 out of 4 → 75%
        Total: 8 hits / 10 signals = 80%
        """
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        factor_values = pd.Series(
            [0.5, -0.3, 0.8, -0.1, 0.6, -0.4, 0.2, 0.9, -0.5, 0.3],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 10], names=["date", "asset"],
            ),
        )
        forward_returns = pd.DataFrame(
            {"a": [0.02, -0.01, 0.03, 0.01, -0.02, -0.03, 0.01, 0.04, -0.02, 0.01]},
            index=dates,
        )
        return {"factor_values": factor_values, "forward_returns": forward_returns}

    def test_total_hit_rate(self, data: dict) -> None:
        result = compute_hit_rate(**data)
        assert result["total_hit_rate"] == pytest.approx(8 / 10)

    def test_long_hit_rate(self, data: dict) -> None:
        result = compute_hit_rate(**data)
        assert result["long_hit_rate"] == pytest.approx(5 / 6)

    def test_short_hit_rate(self, data: dict) -> None:
        result = compute_hit_rate(**data)
        assert result["short_hit_rate"] == pytest.approx(3 / 4)

    def test_sample_count(self, data: dict) -> None:
        result = compute_hit_rate(**data)
        assert result["sample_count"] == 10

    def test_custom_threshold(self, data: dict) -> None:
        """With threshold=0.5, long signals: factor > 0.5 (strict).

        factor=0.5 is NOT > 0.5, so index 0 excluded.
        Long: indices 2(0.8), 4(0.6), 7(0.9) → returns: 0.03, -0.02, 0.04
          hits (return > 0): 2, 7 → 2 out of 3 → 66.67%
        """
        result = compute_hit_rate(**data, signal_threshold=0.5)
        assert result["long_hit_rate"] == pytest.approx(2 / 3)

    def test_rolling_hit_rate_length(self, data: dict) -> None:
        result = compute_hit_rate(**data, rolling_window=5)
        assert len(result["rolling_hit_rate"]) == 10

    def test_warning_on_small_sample(self) -> None:
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        fv = pd.Series(
            [0.1, 0.2, 0.3],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 3], names=["date", "asset"],
            ),
        )
        fr = pd.DataFrame({"a": [0.01, 0.02, 0.03]}, index=dates)
        result = compute_hit_rate(fv, fr)
        assert result["warning"] is not None

    def test_exclude_limit_days(self, data: dict) -> None:
        dates = data["forward_returns"].index
        limit = pd.DataFrame(False, index=dates, columns=["a"])
        limit.iloc[0] = True  # exclude first point
        result = compute_hit_rate(
            **data, exclude_limit_days=True, limit_days=limit,
        )
        assert result["sample_count"] == 9
