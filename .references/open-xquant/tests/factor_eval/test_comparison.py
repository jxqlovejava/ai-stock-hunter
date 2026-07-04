"""Tests for multi-asset comparison."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oxq.factor_eval.bundle import create_bundle
from oxq.factor_eval.comparison import compute_asset_comparison


class TestComputeAssetComparison:

    @pytest.fixture()
    def multi_asset_bundle(self):
        """Bundle with 2 assets, 30 dates each, 80 price dates."""
        np.random.seed(42)
        factor_dates = pd.date_range("2024-01-01", periods=30, freq="B")
        price_dates = pd.date_range("2024-01-01", periods=80, freq="B")

        fv_a = np.random.randn(30) * 0.5
        fv_b = np.random.randn(30) * 0.5

        factor_values = pd.Series(
            np.concatenate([fv_a, fv_b]),
            index=pd.MultiIndex.from_arrays(
                [np.tile(factor_dates, 2),
                 ["asset_a"] * 30 + ["asset_b"] * 30],
                names=["date", "asset"],
            ),
        )
        prices = pd.DataFrame(
            {
                "asset_a": 100 * np.exp(np.cumsum(np.random.randn(80) * 0.01)),
                "asset_b": 200 * np.exp(np.cumsum(np.random.randn(80) * 0.01)),
            },
            index=price_dates,
        )
        return create_bundle(factor_values, prices, forward_periods=[1, 5, 10, 20])

    def test_returns_both_assets(self, multi_asset_bundle) -> None:
        result = compute_asset_comparison(multi_asset_bundle, forward_periods=[1, 5])
        assert "asset_a" in result["by_asset"]
        assert "asset_b" in result["by_asset"]

    def test_each_asset_has_metrics(self, multi_asset_bundle) -> None:
        result = compute_asset_comparison(multi_asset_bundle, forward_periods=[1, 5])
        for asset_result in result["by_asset"].values():
            assert "hit_rate" in asset_result
            assert "profit_loss_ratio" in asset_result
            assert "decay_half_life" in asset_result
            assert "sample_count" in asset_result

    def test_single_asset_skips_comparison(self) -> None:
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        price_dates = pd.date_range("2024-01-01", periods=80, freq="B")
        fv = pd.Series(
            np.random.randn(30),
            index=pd.MultiIndex.from_arrays(
                [dates, ["a"] * 30], names=["date", "asset"],
            ),
        )
        prices = pd.DataFrame(
            {"a": 100 * np.exp(np.cumsum(np.random.randn(80) * 0.01))},
            index=price_dates,
        )
        bundle = create_bundle(fv, prices, forward_periods=[1, 5])
        result = compute_asset_comparison(bundle, forward_periods=[1, 5])
        assert result["skipped"] is True

    def test_sample_counts_are_correct(self, multi_asset_bundle) -> None:
        result = compute_asset_comparison(multi_asset_bundle, forward_periods=[1])
        assert result["by_asset"]["asset_a"]["sample_count"] == 30
        assert result["by_asset"]["asset_b"]["sample_count"] == 30

    def test_result_is_serializable(self, multi_asset_bundle) -> None:
        import json
        result = compute_asset_comparison(multi_asset_bundle, forward_periods=[1, 5])
        for asset_data in result["by_asset"].values():
            asset_data.pop("rolling_hit_rate", None)
            asset_data.pop("decay_correlations", None)
        json.dumps(result)
