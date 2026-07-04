"""Tests for Phase 4 — Tool API timezone and currency serialization."""

from __future__ import annotations

import pandas as pd
import pytest

from oxq.tools import session
from oxq.tools.engine import engine_results, engine_run, engine_trade_list
from oxq.tools.strategy import strategy_create, strategy_add_signal, strategy_inspect


@pytest.fixture(autouse=True)
def _reset_session():
    session.clear()


@pytest.fixture()
def sample_data_dir(tmp_path):
    """Create 120-bar trending data as AAPL.parquet with UTC timezone."""
    n = 120
    dates = pd.bdate_range("2024-01-01", periods=n, tz="UTC")
    closes: list[float] = []
    for i in range(50):
        closes.append(200 - i * 2)
    for i in range(40):
        closes.append(102 + i * 2)
    for i in range(30):
        closes.append(180 - i * 2)

    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000] * n,
        },
        index=dates,
    )
    df.to_parquet(tmp_path / "AAPL.parquet")
    return tmp_path


def _build_strategy(name: str = "sma_cross") -> None:
    strategy_create(
        name=name,
        hypothesis="Test",
        objectives={"total_return": {"min": -0.5}},
    )
    strategy_add_signal(
        strategy=name,
        name="sma_10_x_sma_50",
        type="Crossover",
        params={"fast": "sma_10", "slow": "sma_50"},
        indicators={
            "sma_10": {"type": "SMA", "params": {"period": 10}},
            "sma_50": {"type": "SMA", "params": {"period": 50}},
        },
    )


def test_engine_run_result_includes_currency(sample_data_dir) -> None:
    """engine_run result should include currency field."""
    _build_strategy()
    result = engine_run(
        strategy="sma_cross",
        start="2024-01-01",
        end="2024-12-31",
        symbols=["AAPL"],
        data_dir=str(sample_data_dir),
    )
    assert "error" not in result
    assert "currency" in result["portfolio"], f"Missing currency in: {result['portfolio']}"


def test_engine_trade_list_includes_currency(sample_data_dir) -> None:
    """engine_trade_list should include currency on each trade."""
    _build_strategy()
    run_result = engine_run(
        strategy="sma_cross",
        start="2024-01-01",
        end="2024-12-31",
        symbols=["AAPL"],
        data_dir=str(sample_data_dir),
    )
    assert "error" not in run_result
    run_id = run_result["run_id"]

    trades = engine_trade_list(run_id=run_id)
    assert trades["total_trades"] > 0
    for trade in trades["trades"]:
        assert "currency" in trade, f"Missing currency in trade: {trade}"


def test_engine_trade_list_dates_have_timezone(sample_data_dir) -> None:
    """Trade dates should be ISO 8601 with timezone."""
    _build_strategy()
    run_result = engine_run(
        strategy="sma_cross",
        start="2024-01-01",
        end="2024-12-31",
        symbols=["AAPL"],
        data_dir=str(sample_data_dir),
    )
    run_id = run_result["run_id"]

    trades = engine_trade_list(run_id=run_id)
    for trade in trades["trades"]:
        assert "T" in trade["date"], f"Date not ISO 8601: {trade['date']}"
        assert "+" in trade["date"] or "Z" in trade["date"], (
            f"Date lacks timezone: {trade['date']}"
        )


def test_engine_results_includes_currency(sample_data_dir) -> None:
    """engine_results should include currency in metrics output."""
    _build_strategy()
    run_result = engine_run(
        strategy="sma_cross",
        start="2024-01-01",
        end="2024-12-31",
        symbols=["AAPL"],
        data_dir=str(sample_data_dir),
    )
    run_id = run_result["run_id"]

    results = engine_results(run_id=run_id)
    assert "currency" in results, f"Missing currency in results: {results.keys()}"
