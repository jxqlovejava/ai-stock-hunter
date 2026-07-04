"""Tests for forward return computation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oxq.factor_eval.returns import compute_forward_returns


class TestComputeForwardReturns:
    """Test compute_forward_returns with hand-calculated values."""

    @pytest.fixture()
    def prices(self) -> pd.DataFrame:
        """5-day price series for 2 assets.

        asset_a: 100, 110, 121, 133.1, 146.41  (10% daily)
        asset_b: 200, 190, 180.5, 171.475, 162.90125  (−5% daily)
        """
        dates = pd.date_range("2024-01-01", periods=5, freq="B")
        return pd.DataFrame(
            {
                "asset_a": [100.0, 110.0, 121.0, 133.1, 146.41],
                "asset_b": [200.0, 190.0, 180.5, 171.475, 162.90125],
            },
            index=dates,
        )

    def test_single_period(self, prices: pd.DataFrame) -> None:
        """1-day forward return = next_price / current_price - 1."""
        result = compute_forward_returns(prices, periods=[1])
        fwd1 = result[1]
        # asset_a day0: 110/100 - 1 = 0.10
        assert fwd1.iloc[0]["asset_a"] == pytest.approx(0.10)
        # asset_b day0: 190/200 - 1 = -0.05
        assert fwd1.iloc[0]["asset_b"] == pytest.approx(-0.05)
        # last row should be NaN (no future price)
        assert np.isnan(fwd1.iloc[-1]["asset_a"])

    def test_multi_period(self, prices: pd.DataFrame) -> None:
        """2-day forward return = price[t+2] / price[t] - 1."""
        result = compute_forward_returns(prices, periods=[2])
        fwd2 = result[2]
        # asset_a day0: 121/100 - 1 = 0.21
        assert fwd2.iloc[0]["asset_a"] == pytest.approx(0.21)
        # last 2 rows should be NaN
        assert np.isnan(fwd2.iloc[-1]["asset_a"])
        assert np.isnan(fwd2.iloc[-2]["asset_a"])

    def test_multiple_periods_at_once(self, prices: pd.DataFrame) -> None:
        """Request [1, 3] returns both in one call."""
        result = compute_forward_returns(prices, periods=[1, 3])
        assert set(result.keys()) == {1, 3}
        # 3-day forward return asset_a day0: 133.1/100 - 1 = 0.331
        assert result[3].iloc[0]["asset_a"] == pytest.approx(0.331)

    def test_skip_suspension_days(self, prices: pd.DataFrame) -> None:
        """When suspension_days marks day1, 1-day return from day0 uses day2 price."""
        dates = prices.index
        suspension = pd.DataFrame(
            False, index=dates, columns=prices.columns,
        )
        suspension.loc[dates[1], "asset_a"] = True  # day1 suspended

        result = compute_forward_returns(
            prices, periods=[1], suspension_days=suspension,
        )
        fwd1 = result[1]
        # asset_a day0: skip day1 (suspended), use day2: 121/100 - 1 = 0.21
        assert fwd1.iloc[0]["asset_a"] == pytest.approx(0.21)
        # asset_b day0: day1 not suspended, normal: 190/200 - 1 = -0.05
        assert fwd1.iloc[0]["asset_b"] == pytest.approx(-0.05)
