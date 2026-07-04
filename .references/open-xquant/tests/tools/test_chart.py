"""Tests for chart tools."""

from __future__ import annotations

import os

import pandas as pd
import pytest

from oxq.tools import session
from oxq.tools.engine import engine_run
from oxq.tools.strategy import strategy_add_signal, strategy_create

pytest.importorskip("mplfinance", reason="mplfinance not installed")

from oxq.tools.chart import chart_indicator  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_session():
    session.clear()


@pytest.fixture()
def sample_data_dir(tmp_path):
    """Create 60-bar OHLCV data for AAPL."""
    n = 60
    dates = pd.bdate_range("2024-01-01", periods=n)
    closes = [100.0 + i * 0.5 for i in range(n)]
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 2 for c in closes],
            "low": [c - 2 for c in closes],
            "close": closes,
            "volume": [1_000_000] * n,
        },
        index=dates,
    )
    df.to_parquet(tmp_path / "AAPL.parquet")
    return tmp_path


def _build_and_run(data_dir, run_through="indicator"):
    """Build a strategy with SMA indicator and run through indicator phase."""
    strategy_create(
        name="test_chart",
        hypothesis="test",
        objectives={"total_return": {"min": -1.0}},
    )
    strategy_add_signal(
        strategy="test_chart",
        name="cross",
        type="Crossover",
        params={"fast": "sma_5", "slow": "sma_20"},
        indicators={
            "sma_5": {"type": "SMA", "params": {"column": "close", "period": 5}},
            "sma_20": {"type": "SMA", "params": {"column": "close", "period": 20}},
        },
    )
    result = engine_run(
        strategy="test_chart",
        start="2024-01-01",
        end="2024-03-31",
        symbols=["AAPL"],
        data_dir=str(data_dir),
        run_through=run_through,
    )
    return result["run_id"]


def test_chart_indicator_overlay(sample_data_dir):
    run_id = _build_and_run(sample_data_dir)
    result = chart_indicator(
        run_id=run_id,
        symbol="AAPL",
        columns=["sma_5", "sma_20"],
        overlay=True,
    )
    assert "error" not in result
    assert result["symbol"] == "AAPL"
    assert result["columns"] == ["sma_5", "sma_20"]
    assert os.path.exists(result["path"])
    assert result["path"].endswith(".png")
    os.unlink(result["path"])


def test_chart_indicator_subplot(sample_data_dir):
    run_id = _build_and_run(sample_data_dir)
    result = chart_indicator(
        run_id=run_id,
        symbol="AAPL",
        columns=["sma_5"],
        overlay=False,
    )
    assert "error" not in result
    assert os.path.exists(result["path"])
    os.unlink(result["path"])


def test_chart_indicator_run_not_found():
    result = chart_indicator(
        run_id="nonexistent",
        symbol="AAPL",
        columns=["sma_5"],
    )
    assert "error" in result
    assert "not found" in result["error"]


def test_chart_indicator_symbol_not_found(sample_data_dir):
    run_id = _build_and_run(sample_data_dir)
    result = chart_indicator(
        run_id=run_id,
        symbol="GOOG",
        columns=["sma_5"],
    )
    assert "error" in result
    assert "GOOG" in result["error"]


def test_chart_indicator_column_not_found(sample_data_dir):
    run_id = _build_and_run(sample_data_dir)
    result = chart_indicator(
        run_id=run_id,
        symbol="AAPL",
        columns=["nonexistent_indicator"],
    )
    assert "error" in result
    assert "nonexistent_indicator" in result["error"]
