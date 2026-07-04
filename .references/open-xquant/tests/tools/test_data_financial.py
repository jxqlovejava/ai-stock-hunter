"""Tests for financial tools in oxq.tools.data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from oxq.tools.data import financial_download, financial_inspect, financial_list


class TestFinancialList:
    def test_empty_dir(self, tmp_path: Path) -> None:
        result = financial_list(data_dir=str(tmp_path))
        assert result["count"] == 0

    def test_with_files(self, tmp_path: Path) -> None:
        fin_dir = tmp_path / "financial"
        fin_dir.mkdir(parents=True)
        df = pd.DataFrame({"eps": [1.0]}, index=pd.DatetimeIndex(["2024-06-30"], name="report_date"))
        df.to_parquet(fin_dir / "600519.parquet")
        result = financial_list(data_dir=str(tmp_path))
        assert result["count"] == 1
        assert "600519" in result["symbols"]


class TestFinancialInspect:
    def test_inspect_existing(self, tmp_path: Path) -> None:
        fin_dir = tmp_path / "financial"
        fin_dir.mkdir(parents=True)
        df = pd.DataFrame(
            {
                "publish_date": pd.to_datetime(["2024-08-24"]),
                "period": ["quarterly"],
                "eps": [29.42],
                "revenue": [8.69e10],
            },
            index=pd.DatetimeIndex(["2024-06-30"], name="report_date"),
        )
        df.to_parquet(fin_dir / "600519.parquet")
        result = financial_inspect(symbol="600519", data_dir=str(tmp_path))
        assert result["symbol"] == "600519"
        assert result["rows"] == 1
        assert "eps" in result["indicators"]

    def test_inspect_missing(self, tmp_path: Path) -> None:
        result = financial_inspect(symbol="999999", data_dir=str(tmp_path))
        assert "error" in result


class TestFinancialDownload:
    def test_unknown_source(self, tmp_path: Path) -> None:
        result = financial_download(
            symbol="600519", start="2024-01-01", end="2024-12-31",
            source="bloomberg", data_dir=str(tmp_path),
        )
        assert "error" in result
