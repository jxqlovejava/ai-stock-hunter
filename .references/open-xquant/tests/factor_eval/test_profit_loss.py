"""Tests for profit/loss ratio computation."""

from __future__ import annotations

import pandas as pd
import pytest

from oxq.factor_eval.profit_loss import compute_profit_loss_ratio


class TestComputeProfitLossRatio:
    """Test profit/loss ratio with hand-calculated values."""

    @pytest.fixture()
    def data(self) -> dict:
        """10-point factor + return series.

        factor:  [0.5, -0.3, 0.8, -0.1, 0.6, -0.4, 0.2, 0.9, -0.5, 0.3]
        returns: [0.02, -0.01, 0.03, 0.01, -0.02, -0.03, 0.01, 0.04, -0.02, 0.01]

        Long signals (factor > 0): indices 0,2,4,6,7,9
          returns: [0.02, 0.03, -0.02, 0.01, 0.04, 0.01]
          wins (>0): [0.02, 0.03, 0.01, 0.04, 0.01] → mean = 0.022
          losses (<0): [-0.02] → mean abs = 0.02
          P/L ratio = 0.022 / 0.02 = 1.1
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

    def test_avg_win(self, data: dict) -> None:
        result = compute_profit_loss_ratio(**data)
        assert result["avg_win"] == pytest.approx(0.022)

    def test_avg_loss(self, data: dict) -> None:
        result = compute_profit_loss_ratio(**data)
        assert result["avg_loss"] == pytest.approx(0.02)

    def test_profit_loss_ratio(self, data: dict) -> None:
        result = compute_profit_loss_ratio(**data)
        assert result["ratio"] == pytest.approx(1.1)

    def test_return_distribution(self, data: dict) -> None:
        result = compute_profit_loss_ratio(**data)
        assert len(result["return_distribution"]) == 6

    def test_rolling_ratio_length(self, data: dict) -> None:
        result = compute_profit_loss_ratio(**data, rolling_window=5)
        assert len(result["rolling_ratio"]) == 10

    def test_warning_on_small_sample(self) -> None:
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        fv = pd.Series(
            [0.1, 0.2, 0.3],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 3], names=["date", "asset"],
            ),
        )
        fr = pd.DataFrame({"a": [0.01, 0.02, 0.03]}, index=dates)
        result = compute_profit_loss_ratio(fv, fr)
        assert result["warning"] is not None

    def test_no_losses_returns_inf(self) -> None:
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        fv = pd.Series(
            [0.5, 0.6, 0.7],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 3], names=["date", "asset"],
            ),
        )
        fr = pd.DataFrame({"a": [0.01, 0.02, 0.03]}, index=dates)
        result = compute_profit_loss_ratio(fv, fr)
        assert result["ratio"] == float("inf")

    def test_date_range_filter(self, data: dict) -> None:
        full = compute_profit_loss_ratio(**data)
        sliced = compute_profit_loss_ratio(
            **data, start_date="2024-01-08", end_date="2024-01-12",
        )
        assert sliced["sample_count"] < full["sample_count"]
