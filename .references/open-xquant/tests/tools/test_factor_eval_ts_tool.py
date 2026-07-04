"""Tests for time-series factor evaluation tool."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oxq.tools.factor_eval_ts import factor_evaluate_ts


@pytest.fixture()
def data_dir(tmp_path: Path) -> str:
    """Create sample parquet files for 2 symbols."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=300, freq="B")
    for sym in ["AAPL", "GOOG"]:
        prices = 100 * np.exp(np.cumsum(np.random.randn(300) * 0.01))
        df = pd.DataFrame(
            {
                "open": prices * 0.99,
                "high": prices * 1.01,
                "low": prices * 0.98,
                "close": prices,
                "volume": np.random.randint(1000, 10000, 300).astype(float),
            },
            index=dates,
        )
        df.to_parquet(tmp_path / f"{sym}.parquet")
    return str(tmp_path)


class TestFactorEvaluateTs:

    def test_basic_evaluation(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            indicator="SMA",
            params={"column": "close", "period": 10},
            symbols=["AAPL"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
            forward_periods=[1, 5],
            t1_offset=False,
        )
        assert "error" not in result
        assert "metrics" in result
        assert "hit_rate" in result["metrics"]
        assert "decay_curve" in result["metrics"]
        assert "profit_loss" in result["metrics"]
        assert "cash_period" in result["metrics"]

    def test_returns_charts(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            indicator="SMA",
            params={"column": "close", "period": 10},
            symbols=["AAPL"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
            forward_periods=[1, 5],
            t1_offset=False,
        )
        assert "charts" in result
        for path in result["charts"].values():
            assert os.path.exists(path)

    def test_multi_asset_includes_comparison(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            indicator="SMA",
            params={"column": "close", "period": 10},
            symbols=["AAPL", "GOOG"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
            forward_periods=[1, 5],
            t1_offset=False,
        )
        assert result["metrics"]["comparison"] is not None
        assert result["metrics"]["comparison"]["skipped"] is False

    def test_single_asset_skips_comparison(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            indicator="SMA",
            params={"column": "close", "period": 10},
            symbols=["AAPL"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
            forward_periods=[1, 5],
            t1_offset=False,
        )
        assert (
            result["metrics"]["comparison"] is None
            or result["metrics"]["comparison"]["skipped"] is True
        )

    def test_unknown_indicator_returns_error(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            indicator="NonExistent",
            params={},
            symbols=["AAPL"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
        )
        assert "error" in result

    def test_missing_data_returns_error(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            indicator="SMA",
            params={"column": "close", "period": 10},
            symbols=["NONEXIST"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
        )
        assert "error" in result

    def test_market_state_method(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            indicator="SMA",
            params={"column": "close", "period": 10},
            symbols=["AAPL"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
            forward_periods=[1, 5],
            t1_offset=False,
            market_state_method="sma",
        )
        assert result["metrics"]["conditional"] is not None
        assert result["metrics"]["conditional"]["skipped"] is False

    def test_factor_column_mode(self, data_dir: str) -> None:
        """Mode 2: evaluate a pre-computed column instead of a registered indicator."""
        # Add a custom factor column to the parquet files
        for sym in ["AAPL"]:
            path = Path(data_dir) / f"{sym}.parquet"
            df = pd.read_parquet(path)
            df["my_factor"] = df["close"].pct_change(5)
            df.to_parquet(path)

        result = factor_evaluate_ts(
            factor_column="my_factor",
            symbols=["AAPL"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
            forward_periods=[1, 5],
            t1_offset=False,
        )
        assert "error" not in result
        assert result["indicator"] == "my_factor"
        assert "hit_rate" in result["metrics"]

    def test_factor_column_missing_returns_error(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            factor_column="nonexistent_column",
            symbols=["AAPL"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
            forward_periods=[1, 5],
        )
        assert "error" in result
        assert "nonexistent_column" in result["error"]

    def test_neither_indicator_nor_column_returns_error(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            symbols=["AAPL"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
        )
        assert "error" in result

    def test_run_id_mode(self, data_dir: str) -> None:
        """Mode 3: read factor column from engine_run result via session."""
        from dataclasses import dataclass, field

        from oxq.tools import session

        # Create a mock RunResult with mktdata containing a custom column
        dates = pd.date_range("2023-01-01", periods=300, freq="B")
        prices = 100 * np.exp(np.cumsum(np.random.RandomState(42).randn(300) * 0.01))
        df = pd.DataFrame(
            {
                "open": prices * 0.99,
                "high": prices * 1.01,
                "low": prices * 0.98,
                "close": prices,
                "volume": np.random.RandomState(42).randint(1000, 10000, 300).astype(float),
                "my_composite": np.random.RandomState(42).randn(300),
            },
            index=dates,
        )

        @dataclass
        class MockRunResult:
            mktdata: dict = field(default_factory=dict)

        mock_result = MockRunResult(mktdata={"AAPL": df})
        session._run_results["test_run_123"] = mock_result

        try:
            result = factor_evaluate_ts(
                run_id="test_run_123",
                factor_column="my_composite",
                symbols=["AAPL"],
                start="2023-01-01",
                end="2023-12-31",
                forward_periods=[1, 5],
                t1_offset=False,
            )
            assert "error" not in result, result.get("error")
            assert result["indicator"] == "my_composite"
            assert "hit_rate" in result["metrics"]
        finally:
            session._run_results.pop("test_run_123", None)

    def test_run_id_not_found_returns_error(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            run_id="nonexistent_run",
            factor_column="col",
            symbols=["AAPL"],
            start="2023-01-01",
            end="2023-12-31",
        )
        assert "error" in result
        assert "nonexistent_run" in result["error"]

    def test_config_in_result(self, data_dir: str) -> None:
        result = factor_evaluate_ts(
            indicator="SMA",
            params={"column": "close", "period": 10},
            symbols=["AAPL"],
            start="2023-01-01",
            end="2023-12-31",
            data_dir=data_dir,
            forward_periods=[1, 5],
            t1_offset=False,
            signal_threshold=0.5,
        )
        assert result["config"]["signal_threshold"] == 0.5
        assert result["config"]["t1_offset"] is False
