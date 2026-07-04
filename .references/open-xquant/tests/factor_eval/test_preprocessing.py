"""Tests for A-share preprocessing functions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oxq.factor_eval.preprocessing import (
    apply_t1_offset,
    mark_limit_days,
    mark_suspension_days,
)


class TestApplyT1Offset:
    """Test T+1 factor offset."""

    def test_shifts_factor_by_one_trading_day(self) -> None:
        dates = pd.date_range("2024-01-01", periods=5, freq="B")
        prices = pd.DataFrame({"a": range(5)}, index=dates, dtype=float)

        from oxq.factor_eval.bundle import AlignmentReport, FactorBundle

        factor_values = pd.Series(
            [1.0, 2.0, 3.0, 4.0, 5.0],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 5],
                names=["date", "asset"],
            ),
        )
        report = AlignmentReport(5, 5, 0.0, [], [], 0, 0.0, 0, 0.0)
        bundle = FactorBundle(factor_values, prices, report)

        shifted = apply_t1_offset(bundle)
        # Original day0 factor (1.0) should now be at day1
        shifted_dates = shifted.factor_values.index.get_level_values("date")
        assert shifted_dates[0] == dates[1]
        assert shifted.factor_values.iloc[0] == 1.0
        # Last factor value dropped (no next trading day in range)
        assert len(shifted.factor_values) == 4

    def test_returns_new_bundle(self) -> None:
        """Should not mutate original bundle."""
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        prices = pd.DataFrame({"a": range(3)}, index=dates, dtype=float)

        from oxq.factor_eval.bundle import AlignmentReport, FactorBundle

        factor_values = pd.Series(
            [1.0, 2.0, 3.0],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 3],
                names=["date", "asset"],
            ),
        )
        report = AlignmentReport(3, 3, 0.0, [], [], 0, 0.0, 0, 0.0)
        bundle = FactorBundle(factor_values, prices, report)

        shifted = apply_t1_offset(bundle)
        assert len(bundle.factor_values) == 3  # original unchanged
        assert len(shifted.factor_values) == 2


class TestMarkLimitDays:
    """Test limit-up/down day detection."""

    def test_detects_10pct_limit_mainboard(self) -> None:
        """SH/SZ mainboard: +/-10% triggers limit."""
        dates = pd.date_range("2024-01-01", periods=4, freq="B")
        # day1: +10% (limit up), day2: -10% (limit down), day3: +5% (normal)
        prices = pd.DataFrame(
            {"600001": [100.0, 110.0, 99.0, 103.95]},
            index=dates,
        )
        meta = {"600001": {"exchange": "SH", "asset_type": "stock"}}
        result = mark_limit_days(prices, asset_meta=meta)
        assert result.iloc[0]["600001"] is np.bool_(False)  # day0: no prev
        assert result.iloc[1]["600001"] is np.bool_(True)  # +10%
        assert result.iloc[2]["600001"] is np.bool_(True)  # -10%
        assert result.iloc[3]["600001"] is np.bool_(False)  # +5%

    def test_detects_20pct_limit_chinext(self) -> None:
        """ChiNext (30x codes): +/-20% threshold."""
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        prices = pd.DataFrame(
            {"300001": [100.0, 120.0, 96.0]},  # +20%, then -20%
            index=dates,
        )
        meta = {"300001": {"exchange": "SZ", "asset_type": "stock"}}
        result = mark_limit_days(prices, asset_meta=meta)
        assert result.iloc[1]["300001"] is np.bool_(True)  # +20%
        assert result.iloc[2]["300001"] is np.bool_(True)  # -20%

    def test_no_meta_returns_all_false(self) -> None:
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        prices = pd.DataFrame({"AAPL": [100.0, 120.0, 96.0]}, index=dates)
        result = mark_limit_days(prices, asset_meta=None)
        assert not result.any().any()

    def test_us_market_returns_all_false(self) -> None:
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        prices = pd.DataFrame({"AAPL": [100.0, 120.0, 96.0]}, index=dates)
        meta = {"AAPL": {"exchange": "US", "asset_type": "stock"}}
        result = mark_limit_days(prices, asset_meta=meta)
        assert not result.any().any()


class TestMarkSuspensionDays:
    """Test suspension day detection."""

    def test_zero_return_is_suspension(self) -> None:
        """Price unchanged day-over-day = suspension."""
        dates = pd.date_range("2024-01-01", periods=4, freq="B")
        prices = pd.DataFrame(
            {"a": [100.0, 100.0, 105.0, 105.0]},  # day1, day3 unchanged
            index=dates,
        )
        result = mark_suspension_days(prices)
        assert result.iloc[0]["a"] is np.bool_(False)  # first day: no prev
        assert result.iloc[1]["a"] is np.bool_(True)  # unchanged
        assert result.iloc[2]["a"] is np.bool_(False)  # changed
        assert result.iloc[3]["a"] is np.bool_(True)  # unchanged

    def test_zero_volume_is_suspension(self) -> None:
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        prices = pd.DataFrame({"a": [100.0, 105.0, 110.0]}, index=dates)
        volume = pd.DataFrame({"a": [1000, 0, 500]}, index=dates)
        result = mark_suspension_days(prices, volume=volume)
        assert result.iloc[0]["a"] is np.bool_(False)
        assert result.iloc[1]["a"] is np.bool_(True)  # zero volume
        assert result.iloc[2]["a"] is np.bool_(False)
