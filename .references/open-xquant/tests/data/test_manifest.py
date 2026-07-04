from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from oxq.data.manifest import read_manifest, verify_manifest, write_manifest


@pytest.fixture()
def sample_parquet(tmp_path: Path) -> Path:
    df = pd.DataFrame(
        {"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [100]},
        index=pd.DatetimeIndex(["2024-01-02"], name="date"),
    )
    path = tmp_path / "TEST.parquet"
    df.to_parquet(path)
    return path


class TestWriteAndReadManifest:
    def test_roundtrip(self, sample_parquet: Path) -> None:
        manifest_path = write_manifest(
            parquet_path=sample_parquet,
            symbol="TEST",
            provider="yfinance",
            start="2024-01-01",
            end="2024-12-31",
            rows=1,
            extra={"auto_adjust": True},
        )
        assert manifest_path == sample_parquet.parent / "TEST.manifest.json"
        data = read_manifest(manifest_path)
        assert data is not None
        assert data["symbol"] == "TEST"
        assert data["provider"] == "yfinance"
        assert data["start"] == "2024-01-01"
        assert data["end"] == "2024-12-31"
        assert data["rows"] == 1
        assert data["extra"] == {"auto_adjust": True}
        assert "sha256" in data
        assert "created_at" in data

    def test_sha256_correctness(self, sample_parquet: Path) -> None:
        write_manifest(
            parquet_path=sample_parquet,
            symbol="TEST",
            provider="yfinance",
            start="2024-01-01",
            end="2024-12-31",
            rows=1,
        )
        manifest_path = sample_parquet.parent / "TEST.manifest.json"
        data = read_manifest(manifest_path)
        expected_sha = hashlib.sha256(sample_parquet.read_bytes()).hexdigest()
        assert data["sha256"] == expected_sha

    def test_extra_none_omitted(self, sample_parquet: Path) -> None:
        write_manifest(
            parquet_path=sample_parquet,
            symbol="TEST",
            provider="yfinance",
            start="2024-01-01",
            end="2024-12-31",
            rows=1,
        )
        data = read_manifest(sample_parquet.parent / "TEST.manifest.json")
        assert data["extra"] is None

    def test_read_missing_returns_none(self, tmp_path: Path) -> None:
        assert read_manifest(tmp_path / "nope.manifest.json") is None

    def test_read_invalid_json_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.manifest.json"
        bad.write_text("not json{{{")
        assert read_manifest(bad) is None


class TestVerifyManifest:
    def test_real(self, sample_parquet: Path) -> None:
        write_manifest(
            parquet_path=sample_parquet,
            symbol="TEST",
            provider="yfinance",
            start="2024-01-01",
            end="2024-12-31",
            rows=1,
        )
        result = verify_manifest(sample_parquet)
        assert result.status == "real"
        assert result.provider == "yfinance"

    def test_mock(self, sample_parquet: Path) -> None:
        write_manifest(
            parquet_path=sample_parquet,
            symbol="TEST",
            provider="mock",
            start="2024-01-01",
            end="2024-12-31",
            rows=1,
        )
        result = verify_manifest(sample_parquet)
        assert result.status == "mock"
        assert result.provider == "mock"

    def test_missing(self, sample_parquet: Path) -> None:
        result = verify_manifest(sample_parquet)
        assert result.status == "missing"
        assert result.provider is None

    def test_corrupted(self, sample_parquet: Path) -> None:
        write_manifest(
            parquet_path=sample_parquet,
            symbol="TEST",
            provider="yfinance",
            start="2024-01-01",
            end="2024-12-31",
            rows=1,
        )
        # Tamper with parquet after manifest was written
        sample_parquet.write_bytes(b"tampered data")
        result = verify_manifest(sample_parquet)
        assert result.status == "corrupted"
        assert result.provider == "yfinance"


# ---------------------------------------------------------------------------
# Integration tests — manifest written as side effect of downloaders / mock
# ---------------------------------------------------------------------------


class TestMockGeneratorManifest:
    """data_generate_mock must produce a .manifest.json per symbol."""

    def test_mock_manifest_written(self, tmp_path: Path) -> None:
        from oxq.tools.data import data_generate_mock

        data_generate_mock(
            symbols=["A", "B"],
            start="2024-01-01",
            end="2024-03-31",
            seed=42,
            data_dir=str(tmp_path),
        )
        for sym in ["A", "B"]:
            manifest_path = tmp_path / f"{sym}.manifest.json"
            assert manifest_path.exists(), f"{sym}.manifest.json missing"
            data = read_manifest(manifest_path)
            assert data["provider"] == "mock"
            assert data["symbol"] == sym
            assert data["extra"]["seed"] == 42

    def test_mock_manifest_verifies_as_mock(self, tmp_path: Path) -> None:
        from oxq.tools.data import data_generate_mock

        data_generate_mock(
            symbols=["X"],
            start="2024-01-01",
            end="2024-03-31",
            data_dir=str(tmp_path),
        )
        result = verify_manifest(tmp_path / "X.parquet")
        assert result.status == "mock"
        assert result.provider == "mock"

    def test_mock_manifest_sha256_matches_parquet(self, tmp_path: Path) -> None:
        import hashlib

        from oxq.tools.data import data_generate_mock

        data_generate_mock(
            symbols=["Z"],
            start="2024-01-01",
            end="2024-03-31",
            data_dir=str(tmp_path),
        )
        parquet_path = tmp_path / "Z.parquet"
        data = read_manifest(tmp_path / "Z.manifest.json")
        expected = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        assert data["sha256"] == expected
