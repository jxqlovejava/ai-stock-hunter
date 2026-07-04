"""Tests for financial and macro mock data generation.

Validates that data_generate_mock with financial=True / macro=True
produces parquet files matching the schemas of EastMoneyFetcher and
WorldBankFetcher, is deterministic, and integrates with inspect tools.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from oxq.data.factors import FINANCIAL_INDICATORS, MACRO_INDICATOR_MAP, resolve_factor_dir
from oxq.tools.data import data_generate_mock, financial_inspect

# ── Financial tests ──────────────────────────────────────────────────


def test_generate_mock_financial_schema(tmp_path: Path):
    """Generated financial parquet matches EastMoneyFetcher output schema."""
    data_generate_mock(
        symbols=["A", "B"],
        start="2020-01-01",
        end="2024-12-31",
        seed=42,
        financial=True,
        data_dir=str(tmp_path),
    )
    fin_dir = resolve_factor_dir(tmp_path, sub="financial")
    for sym in ["A", "B"]:
        path = fin_dir / f"{sym}.parquet"
        assert path.exists(), f"{sym}.parquet missing"
        df = pd.read_parquet(path)

        # Index
        assert df.index.name == "report_date"
        assert pd.api.types.is_datetime64_any_dtype(df.index)

        # Must contain all FINANCIAL_INDICATORS + metadata columns
        expected_indicators = set(FINANCIAL_INDICATORS)
        actual_cols = set(df.columns)
        assert expected_indicators.issubset(actual_cols), (
            f"Missing columns: {expected_indicators - actual_cols}"
        )
        assert "publish_date" in actual_cols
        assert "period" in actual_cols

        # Numeric columns are float
        for col in FINANCIAL_INDICATORS:
            assert pd.api.types.is_float_dtype(df[col]), f"{col} is not float"

        assert len(df) > 0


def test_generate_mock_financial_deterministic(tmp_path: Path):
    """Same seed produces identical financial DataFrames."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    for d in [dir_a, dir_b]:
        data_generate_mock(
            symbols=["X"],
            start="2020-01-01",
            end="2024-12-31",
            seed=99,
            financial=True,
            data_dir=str(d),
        )

    df_a = pd.read_parquet(resolve_factor_dir(dir_a, sub="financial") / "X.parquet")
    df_b = pd.read_parquet(resolve_factor_dir(dir_b, sub="financial") / "X.parquet")
    pd.testing.assert_frame_equal(df_a, df_b)


def test_generate_mock_financial_per_symbol_different(tmp_path: Path):
    """Different symbols produce different financial data paths."""
    data_generate_mock(
        symbols=["A", "B"],
        start="2020-01-01",
        end="2024-12-31",
        seed=42,
        financial=True,
        data_dir=str(tmp_path),
    )
    fin_dir = resolve_factor_dir(tmp_path, sub="financial")
    df_a = pd.read_parquet(fin_dir / "A.parquet")
    df_b = pd.read_parquet(fin_dir / "B.parquet")
    assert not df_a["roe"].equals(df_b["roe"])
    assert not df_a["pb"].equals(df_b["pb"])


def test_generate_mock_financial_range(tmp_path: Path):
    """Financial indicator values stay within plausible ranges."""
    data_generate_mock(
        symbols=["R1", "R2", "R3"],
        start="2018-01-01",
        end="2024-12-31",
        seed=7,
        financial=True,
        data_dir=str(tmp_path),
    )
    fin_dir = resolve_factor_dir(tmp_path, sub="financial")
    for sym in ["R1", "R2", "R3"]:
        df = pd.read_parquet(fin_dir / f"{sym}.parquet")
        assert (df["roe"] >= 0).all() and (df["roe"] <= 0.5).all(), "ROE out of range"
        assert (df["pb"] >= 0.1).all() and (df["pb"] <= 30).all(), "PB out of range"
        assert (df["pe_ttm"] >= 1).all() and (df["pe_ttm"] <= 100).all(), "PE_TTM out of range"
        assert (df["revenue"] > 0).all(), "revenue must be positive"
        assert (df["total_assets"] > 0).all(), "total_assets must be positive"
        assert (df["net_income"] > 0).all(), "net_income must be positive"


# ── Macro tests ──────────────────────────────────────────────────────


def test_generate_mock_macro_schema(tmp_path: Path):
    """Generated macro parquet matches WorldBankFetcher output schema."""
    data_generate_mock(
        symbols=["DUMMY"],
        start="2015-01-01",
        end="2024-12-31",
        seed=42,
        macro=True,
        macro_countries=["CHN", "USA", "JPN"],
        data_dir=str(tmp_path),
    )
    macro_dir = resolve_factor_dir(tmp_path, sub="macro")
    for indicator in MACRO_INDICATOR_MAP:
        path = macro_dir / f"{indicator}.parquet"
        assert path.exists(), f"{indicator}.parquet missing"
        df = pd.read_parquet(path)

        # Index
        assert df.index.name == "year"
        assert pd.api.types.is_integer_dtype(df.index)

        # Columns = sorted country codes
        assert list(df.columns) == sorted(["CHN", "USA", "JPN"])

        # Values are float
        for col in df.columns:
            assert pd.api.types.is_float_dtype(df[col])

        assert len(df) > 0


def test_generate_mock_macro_deterministic(tmp_path: Path):
    """Same seed produces identical macro DataFrames."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    for d in [dir_a, dir_b]:
        data_generate_mock(
            symbols=["DUMMY"],
            start="2015-01-01",
            end="2024-12-31",
            seed=42,
            macro=True,
            data_dir=str(d),
        )

    macro_a = resolve_factor_dir(dir_a, sub="macro")
    macro_b = resolve_factor_dir(dir_b, sub="macro")
    for indicator in MACRO_INDICATOR_MAP:
        df_a = pd.read_parquet(macro_a / f"{indicator}.parquet")
        df_b = pd.read_parquet(macro_b / f"{indicator}.parquet")
        pd.testing.assert_frame_equal(df_a, df_b)


# ── Backward compatibility ───────────────────────────────────────────


def test_generate_mock_backward_compat(tmp_path: Path):
    """Default params (financial=False, macro=False) produce no factor data."""
    result = data_generate_mock(
        symbols=["BC"],
        start="2024-01-01",
        end="2024-03-31",
        seed=42,
        data_dir=str(tmp_path),
    )
    # Return dict has no new keys
    assert "financial" not in result
    assert "macro" not in result

    # No financial/macro subdirectories created
    fin_dir = resolve_factor_dir(tmp_path, sub="financial")
    macro_dir = resolve_factor_dir(tmp_path, sub="macro")
    assert not fin_dir.exists(), "financial dir should not exist"
    assert not macro_dir.exists(), "macro dir should not exist"


# ── Integration ──────────────────────────────────────────────────────


def test_generate_mock_financial_readable_by_financial_inspect(tmp_path: Path):
    """financial_inspect can read mock-generated financial data."""
    data_generate_mock(
        symbols=["INTG"],
        start="2020-01-01",
        end="2024-12-31",
        seed=42,
        financial=True,
        data_dir=str(tmp_path),
    )
    result = financial_inspect(symbol="INTG", data_dir=str(tmp_path))
    assert "error" not in result
    assert result["rows"] > 0
    assert len(result["indicators"]) > 0
    assert "roe" in result["indicators"]
    assert "pb" in result["indicators"]
