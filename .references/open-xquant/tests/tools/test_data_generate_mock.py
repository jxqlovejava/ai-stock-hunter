"""Plan 028: data_generate_mock — synthetic OHLCV producer for verifying
strategy pipelines without real market data.

Same on-disk shape as data_load_symbols (parquet files in data_dir,
columns open/high/low/close/volume, DatetimeIndex named 'date',
volume int64) so downstream consumers (data_inspect, factor_evaluate,
engine_run) work unchanged.

Ref: xquant-studio/docs/plans/2026-04-07-028-impl-data-generate-mock.md
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from oxq.tools.data import data_generate_mock, inspect_symbol, list_symbols


def test_writes_parquet_with_correct_shape(tmp_path: Path):
    result = data_generate_mock(
        symbols=["SYM_A", "SYM_B"],
        start="2024-01-01",
        end="2024-03-31",
        data_dir=str(tmp_path),
    )
    assert set(result["symbols"]) == {"SYM_A", "SYM_B"}
    assert "errors" not in result
    for sym in ["SYM_A", "SYM_B"]:
        path = tmp_path / f"{sym}.parquet"
        assert path.exists(), f"{sym}.parquet missing"
        df = pd.read_parquet(path)
        # Plan 036A: market column is now part of the standard schema
        # so cross-asset indicators (CAPM Beta, market-neutral spreads,
        # relative strength) can compute against a benchmark series
        # without needing a separate data source.
        assert set(df.columns) == {"open", "high", "low", "close", "volume", "market"}
        assert df.index.name == "date"
        assert df["volume"].dtype == "int64"
        assert len(df) > 0


def test_is_deterministic_given_seed(tmp_path: Path):
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    data_generate_mock(
        symbols=["X"], start="2024-01-01", end="2024-03-31",
        seed=42, data_dir=str(a_dir),
    )
    data_generate_mock(
        symbols=["X"], start="2024-01-01", end="2024-03-31",
        seed=42, data_dir=str(b_dir),
    )
    df_a = pd.read_parquet(a_dir / "X.parquet")
    df_b = pd.read_parquet(b_dir / "X.parquet")
    pd.testing.assert_frame_equal(df_a, df_b)


def test_different_symbols_have_different_paths(tmp_path: Path):
    data_generate_mock(
        symbols=["A", "B"], start="2024-01-01", end="2024-03-31",
        seed=7, data_dir=str(tmp_path),
    )
    df_a = pd.read_parquet(tmp_path / "A.parquet")
    df_b = pd.read_parquet(tmp_path / "B.parquet")
    # Same length, but different paths.
    assert len(df_a) == len(df_b)
    assert not df_a["close"].equals(df_b["close"])


def test_high_low_invariants_hold(tmp_path: Path):
    data_generate_mock(
        symbols=["INV"], start="2023-01-01", end="2024-12-31",
        data_dir=str(tmp_path),
    )
    df = pd.read_parquet(tmp_path / "INV.parquet")
    body_max = df[["open", "close"]].max(axis=1)
    body_min = df[["open", "close"]].min(axis=1)
    assert (df["high"] >= body_max - 1e-9).all(), "high < max(open, close)"
    assert (df["low"] <= body_min + 1e-9).all(), "low > min(open, close)"
    assert (df["high"] >= df["low"]).all()
    assert (df["close"] > 0).all()


def test_returns_same_shape_as_data_load_symbols(tmp_path: Path):
    result = data_generate_mock(
        symbols=["S1", "S2", "S3"],
        start="2024-01-01", end="2024-03-31",
        data_dir=str(tmp_path),
    )
    assert set(result.keys()) >= {"symbols", "rows", "data_dir"}
    assert "errors" not in result
    for sym in ["S1", "S2", "S3"]:
        assert sym in result["rows"]
        assert result["rows"][sym] > 0


def test_market_column_is_shared_across_symbols(tmp_path: Path):
    """Plan 036A: every symbol's parquet must contain a 'market' column,
    and that column must be IDENTICAL across all symbols (not symbol-
    specific noise). This is the contract that lets cross-asset
    indicators like CAPM Beta compute against a single benchmark
    series via mktdata['market']."""
    data_generate_mock(
        symbols=["A", "B", "C"],
        start="2024-01-01",
        end="2024-06-30",
        seed=99,
        data_dir=str(tmp_path),
    )
    df_a = pd.read_parquet(tmp_path / "A.parquet")
    df_b = pd.read_parquet(tmp_path / "B.parquet")
    df_c = pd.read_parquet(tmp_path / "C.parquet")

    assert "market" in df_a.columns
    pd.testing.assert_series_equal(df_a["market"], df_b["market"], check_names=False)
    pd.testing.assert_series_equal(df_a["market"], df_c["market"], check_names=False)

    # Sanity: not constant, not NaN, same length as close column.
    assert df_a["market"].notna().all()
    assert df_a["market"].nunique() > 1
    assert len(df_a["market"]) == len(df_a["close"])
    # Market column index must align with the price index.
    pd.testing.assert_index_equal(df_a["market"].index, df_a["close"].index)


def test_market_column_enables_capm_beta_computation(tmp_path: Path):
    """Plan 036A+B: a CAPM-style RollingBeta indicator must be
    computable against the schema data_generate_mock now produces.
    This pins the contract referenced in create-indicator.md so that
    a regression in either side breaks the test."""
    import pandas as pd

    data_generate_mock(
        symbols=["X", "Y"],
        start="2023-01-01",
        end="2024-12-31",
        seed=7,
        data_dir=str(tmp_path),
    )
    df_x = pd.read_parquet(tmp_path / "X.parquet")

    # The exact RollingBeta template from create-indicator.md.
    asset_returns = df_x["close"].pct_change()
    market_returns = df_x["market"].pct_change()
    period = 60
    cov = asset_returns.rolling(period).cov(market_returns)
    var = market_returns.rolling(period).var()
    beta = cov / var

    # Beyond the warm-up window, beta is finite and not all-zero.
    tail = beta.iloc[period + 5:]
    assert tail.notna().all()
    assert tail.abs().sum() > 0


def test_inspect_and_list_symbols_find_mock_data(tmp_path: Path):
    """Cross-tool integration: data_inspect and data_list_symbols see
    mock-generated parquets without modification."""
    data_generate_mock(
        symbols=["MOCK1", "MOCK2"],
        start="2024-01-01", end="2024-03-31",
        data_dir=str(tmp_path),
    )
    listed = list_symbols(data_dir=str(tmp_path))
    assert set(listed["symbols"]) == {"MOCK1", "MOCK2"}
    inspected = inspect_symbol(symbol="MOCK1", data_dir=str(tmp_path))
    assert "error" not in inspected
    assert inspected["rows"] > 0
    assert "open" in inspected["columns"]
    assert "close" in inspected["columns"]
