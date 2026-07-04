"""Tests for cash period value analysis."""

from __future__ import annotations

import pandas as pd
import pytest

from oxq.factor_eval.cash_period import compute_cash_period_value


class TestComputeCashPeriodValue:

    @pytest.fixture()
    def data(self) -> dict:
        """10-point factor + return series.

        factor:  [0.5, -0.3, 0.8, -0.1, 0.6, -0.4, 0.2, 0.9, -0.5, 0.3]
        returns: [0.02, -0.01, 0.03, 0.01, -0.02, -0.03, 0.01, 0.04, -0.02, 0.01]

        threshold = 0:
        Holding (factor > 0): indices 0,2,4,6,7,9 → returns [0.02, 0.03, -0.02, 0.01, 0.04, 0.01]
          mean = 0.015
        Cash (factor <= 0): indices 1,3,5,8 → returns [-0.01, 0.01, -0.03, -0.02]
          mean = -0.0125
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

    def test_holding_avg_return(self, data: dict) -> None:
        result = compute_cash_period_value(**data)
        assert result["holding_avg_return"] == pytest.approx(0.015)

    def test_cash_avg_return(self, data: dict) -> None:
        result = compute_cash_period_value(**data)
        assert result["cash_avg_return"] == pytest.approx(-0.0125)

    def test_return_spread(self, data: dict) -> None:
        result = compute_cash_period_value(**data)
        assert result["return_spread"] == pytest.approx(0.0275)

    def test_cash_max_loss(self, data: dict) -> None:
        result = compute_cash_period_value(**data)
        assert result["cash_max_loss"] == pytest.approx(-0.03)

    def test_period_ratios(self, data: dict) -> None:
        result = compute_cash_period_value(**data)
        assert result["holding_ratio"] == pytest.approx(0.6)
        assert result["cash_ratio"] == pytest.approx(0.4)

    def test_no_overlap(self, data: dict) -> None:
        result = compute_cash_period_value(**data)
        assert result["holding_count"] + result["cash_count"] == result["total_count"]

    def test_warning_on_small_sample(self) -> None:
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        fv = pd.Series(
            [0.1, 0.2, 0.3],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 3], names=["date", "asset"],
            ),
        )
        fr = pd.DataFrame({"a": [0.01, 0.02, 0.03]}, index=dates)
        result = compute_cash_period_value(fv, fr)
        assert result["warning"] is not None
