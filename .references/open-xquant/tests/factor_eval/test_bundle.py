"""Tests for FactorBundle construction and alignment."""

from __future__ import annotations

import pandas as pd
import pytest

from oxq.factor_eval.bundle import AlignmentReport, FactorBundle, create_bundle


class TestCreateBundle:
    """Test FactorBundle construction and alignment logic."""

    @pytest.fixture()
    def basic_inputs(self) -> dict:
        """Factor values and prices with partial overlap.

        Factor dates: Jan 1-5 (5 days)
        Price dates: Jan 1-8 (6 business days, covers +3 forward)
        """
        factor_dates = pd.date_range("2024-01-01", periods=5, freq="B")
        price_dates = pd.date_range("2024-01-01", periods=8, freq="B")
        factor_values = pd.Series(
            [0.5, -0.3, 0.8, -0.1, 0.6],
            index=pd.MultiIndex.from_arrays(
                [factor_dates, ["asset_a"] * 5],
                names=["date", "asset"],
            ),
        )
        prices = pd.DataFrame(
            {"asset_a": [100, 101, 102, 103, 104, 105, 106, 107]},
            index=price_dates,
        )
        return {"factor_values": factor_values, "prices": prices}

    def test_creates_bundle(self, basic_inputs: dict) -> None:
        bundle = create_bundle(**basic_inputs, forward_periods=[3])
        assert isinstance(bundle, FactorBundle)
        assert isinstance(bundle.alignment_report, AlignmentReport)

    def test_alignment_report_counts(self, basic_inputs: dict) -> None:
        bundle = create_bundle(**basic_inputs, forward_periods=[3])
        report = bundle.alignment_report
        assert report.original_factor_count == 5
        assert report.aligned_count == 5  # all factor dates in price dates
        assert report.loss_ratio == pytest.approx(0.0)

    def test_factor_dates_outside_prices_dropped(self) -> None:
        """Factor has dates that prices don't — those get dropped."""
        factor_dates = pd.date_range("2024-01-01", periods=5, freq="B")
        price_dates = pd.date_range("2024-01-03", periods=6, freq="B")  # starts later
        factor_values = pd.Series(
            [0.1, 0.2, 0.3, 0.4, 0.5],
            index=pd.MultiIndex.from_arrays(
                [factor_dates, ["a"] * 5], names=["date", "asset"],
            ),
        )
        prices = pd.DataFrame({"a": range(6)}, index=price_dates, dtype=float)
        bundle = create_bundle(factor_values, prices, forward_periods=[1])
        assert bundle.alignment_report.original_factor_count == 5
        assert bundle.alignment_report.aligned_count == 3  # Jan 3,4,5
        assert bundle.alignment_report.loss_ratio == pytest.approx(2 / 5)
        assert len(bundle.alignment_report.dropped_dates) == 2

    def test_insufficient_price_coverage_raises(self) -> None:
        """Prices must extend max(forward_periods) beyond factor dates."""
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        factor_values = pd.Series(
            [0.1, 0.2, 0.3],
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 3], names=["date", "asset"],
            ),
        )
        prices = pd.DataFrame({"a": [100, 101, 102]}, index=dates, dtype=float)
        with pytest.raises(ValueError, match="coverage"):
            create_bundle(factor_values, prices, forward_periods=[5])

    def test_defaults_none_for_optional_fields(self, basic_inputs: dict) -> None:
        bundle = create_bundle(**basic_inputs, forward_periods=[1])
        assert bundle.limit_days is None
        assert bundle.suspension_days is None
        assert bundle.market_state is None
        assert bundle.asset_meta is None

    def test_passes_through_optional_fields(self, basic_inputs: dict) -> None:
        ms = pd.Series(
            ["trend"] * 5,
            index=pd.date_range("2024-01-01", periods=5, freq="B"),
        )
        meta = {"asset_a": {"exchange": "SH", "asset_type": "stock"}}
        bundle = create_bundle(
            **basic_inputs,
            forward_periods=[1],
            market_state=ms,
            asset_meta=meta,
        )
        assert bundle.market_state is not None
        assert bundle.asset_meta == meta

    def test_alignment_report_to_dict(self, basic_inputs: dict) -> None:
        bundle = create_bundle(**basic_inputs, forward_periods=[1])
        d = bundle.alignment_report.to_dict()
        assert isinstance(d, dict)
        assert "original_factor_count" in d
        assert "aligned_count" in d
