"""Tests for the factor_evaluate tool — end-to-end integration."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oxq.tools import session
from oxq.tools.factor_eval import factor_evaluate


@pytest.fixture(autouse=True)
def _reset_session():
    session.clear()


@pytest.fixture()
def multi_symbol_data(tmp_path):
    """Create 5 symbols x 100 bars with trending data."""
    n = 100
    dates = pd.bdate_range("2024-01-01", periods=n)
    symbols = ["AAPL", "GOOG", "MSFT", "AMZN", "META"]
    np.random.seed(42)

    for i, sym in enumerate(symbols):
        base = 100 + i * 20
        noise = np.cumsum(np.random.randn(n) * 0.5)
        trend = np.linspace(0, 10 * (i + 1), n)
        close = base + trend + noise
        df = pd.DataFrame(
            {
                "open": close + np.random.randn(n) * 0.1,
                "high": close + abs(np.random.randn(n) * 0.5),
                "low": close - abs(np.random.randn(n) * 0.5),
                "close": close,
                "volume": np.random.randint(1000, 10000, n).astype(float),
            },
            index=dates,
        )
        df.to_parquet(tmp_path / f"{sym}.parquet")
    return tmp_path, symbols


def test_factor_evaluate_returns_structured_report(multi_symbol_data):
    """Tool returns a complete structured report with all expected keys."""
    data_dir, symbols = multi_symbol_data
    result = factor_evaluate(
        indicator="SMA",
        params={"column": "close", "period": 10},
        symbols=symbols,
        start="2024-01-01",
        end="2024-12-31",
        data_dir=str(data_dir),
    )
    assert "error" not in result
    assert result["indicator"] == "SMA"
    assert result["symbols_count"] == 5
    assert "metrics" in result
    assert "ic" in result["metrics"]
    assert "rank_ic" in result["metrics"]
    assert "icir" in result["metrics"]
    assert "decay" in result["metrics"]
    assert "turnover" in result["metrics"]
    assert "ts_ic" in result["metrics"]
    assert "mean" in result["metrics"]["ts_ic"]
    assert "per_symbol" in result["metrics"]["ts_ic"]
    assert "ic_series" in result


def test_factor_evaluate_warns_on_few_symbols(multi_symbol_data):
    """Should warn when fewer than 30 symbols."""
    data_dir, symbols = multi_symbol_data
    result = factor_evaluate(
        indicator="SMA",
        params={"column": "close", "period": 10},
        symbols=symbols[:2],
        start="2024-01-01",
        end="2024-12-31",
        data_dir=str(data_dir),
    )
    assert "error" not in result
    assert any("symbols_count" in w for w in result["warnings"])


def test_factor_evaluate_unknown_indicator():
    """Should return error for non-existent indicator."""
    result = factor_evaluate(
        indicator="NonExistent",
        params={},
        symbols=["AAPL"],
        start="2024-01-01",
        end="2024-12-31",
    )
    assert "error" in result


def test_factor_evaluate_missing_data(tmp_path):
    """Should return error when symbol data is missing."""
    result = factor_evaluate(
        indicator="SMA",
        params={"column": "close", "period": 10},
        symbols=["AAPL"],
        start="2024-01-01",
        end="2024-12-31",
        data_dir=str(tmp_path),
    )
    assert "error" in result


def test_factor_evaluate_custom_config(multi_symbol_data):
    """Custom eval_config should affect decay horizons."""
    data_dir, symbols = multi_symbol_data
    result = factor_evaluate(
        indicator="SMA",
        params={"column": "close", "period": 10},
        symbols=symbols,
        start="2024-01-01",
        end="2024-12-31",
        data_dir=str(data_dir),
        forward_days=10,
        decay_horizons=[1, 3, 5],
    )
    assert "error" not in result
    assert result["metrics"]["decay"]["horizons"] == [1, 3, 5]
