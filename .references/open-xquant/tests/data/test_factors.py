"""Tests for oxq.data.factors — WorldBankFetcher, FactorDownloader, and read_factor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from oxq.data.factors import (
    MACRO_INDICATOR_MAP,
    FactorDownloader,
    WorldBankFetcher,
    _records_to_dataframe,
    read_factor,
    resolve_factor_dir,
)
from oxq.data.providers import FactorFetcher

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_wb_response(
    indicator_code: str,
    data: dict[tuple[str, int], float | None],
) -> list:
    """Build a fake World Bank API JSON response.

    Parameters
    ----------
    indicator_code : str
        World Bank indicator code.
    data : dict[(country, year), value]
        Mapping of (country_iso3, year) → value.
    """
    records = [
        {
            "indicator": {"id": indicator_code},
            "country": {"id": country},
            "countryiso3code": country,
            "date": str(year),
            "value": value,
        }
        for (country, year), value in data.items()
    ]
    metadata = {"page": 1, "pages": 1, "per_page": 10000, "total": len(records)}
    return [metadata, records]


def _write_sample_factor(
    tmp_path: Path, indicator: str = "gdp", sub: str | None = None,
) -> Path:
    """Write a small sample factor parquet for read tests."""
    df = pd.DataFrame(
        {"CHN": [14.7e12, 17.7e12], "USA": [21.3e12, 23.3e12]},
        index=pd.Index([2020, 2021], name="year"),
    )
    if sub is not None:
        factor_dir = tmp_path / sub
    else:
        factor_dir = tmp_path / "factor"
    factor_dir.mkdir(parents=True, exist_ok=True)
    path = factor_dir / f"{indicator}.parquet"
    df.to_parquet(path)
    return factor_dir


# ---------------------------------------------------------------------------
# resolve_factor_dir
# ---------------------------------------------------------------------------


class TestResolveFactorDir:
    def test_explicit_dir(self, tmp_path: Path) -> None:
        assert resolve_factor_dir(tmp_path) == tmp_path

    def test_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OXQ_DATA_DIR", str(tmp_path))
        assert resolve_factor_dir() == tmp_path / "factor"

    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OXQ_DATA_DIR", raising=False)
        result = resolve_factor_dir()
        assert result == Path.home() / ".oxq" / "data" / "factor"

    def test_sub_appended(self, tmp_path: Path) -> None:
        assert resolve_factor_dir(tmp_path, sub="macro") == tmp_path / "macro"

    def test_sub_with_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OXQ_DATA_DIR", str(tmp_path))
        assert resolve_factor_dir(sub="financial") == tmp_path / "factor" / "financial"

    def test_sub_none_no_change(self, tmp_path: Path) -> None:
        assert resolve_factor_dir(tmp_path, sub=None) == tmp_path


# ---------------------------------------------------------------------------
# _records_to_dataframe
# ---------------------------------------------------------------------------


class TestRecordsToDataframe:
    def test_basic_conversion(self) -> None:
        records = [
            {"date": "2020", "countryiso3code": "USA", "value": 21.3e12},
            {"date": "2020", "countryiso3code": "CHN", "value": 14.7e12},
            {"date": "2021", "countryiso3code": "USA", "value": 23.3e12},
            {"date": "2021", "countryiso3code": "CHN", "value": 17.7e12},
        ]
        df = _records_to_dataframe(records)
        assert df.index.name == "year"
        assert list(df.index) == [2020, 2021]
        assert sorted(df.columns) == ["CHN", "USA"]
        assert df.loc[2020, "USA"] == pytest.approx(21.3e12)

    def test_null_value_becomes_nan(self) -> None:
        records = [
            {"date": "2020", "countryiso3code": "USA", "value": None},
        ]
        df = _records_to_dataframe(records)
        assert pd.isna(df.loc[2020, "USA"])


# ---------------------------------------------------------------------------
# WorldBankFetcher
# ---------------------------------------------------------------------------


class TestWorldBankFetcher:
    def _mock_urlopen(self, response_data: list) -> MagicMock:
        """Create a mock for urllib.request.urlopen."""
        body = json.dumps(response_data).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None
        return mock_resp

    def test_satisfies_protocol(self) -> None:
        fetcher: FactorFetcher = WorldBankFetcher()
        assert isinstance(fetcher, FactorFetcher)

    def test_list_indicators(self) -> None:
        fetcher = WorldBankFetcher()
        indicators = fetcher.list_indicators()
        assert "gdp" in indicators
        assert "cpi" in indicators

    def test_fetch_returns_dataframe(self) -> None:
        wb_response = _make_wb_response("NY.GDP.MKTP.CD", {
            ("USA", 2020): 21.3e12,
            ("CHN", 2020): 14.7e12,
        })
        mock_resp = self._mock_urlopen(wb_response)
        with patch("oxq.data.factors.urllib.request.urlopen", return_value=mock_resp):
            fetcher = WorldBankFetcher()
            df = fetcher.fetch("gdp", "2020", "2020", countries=["USA", "CHN"])
        assert df.index.name == "year"
        assert "USA" in df.columns

    def test_unknown_indicator_raises_value_error(self) -> None:
        fetcher = WorldBankFetcher()
        with pytest.raises(ValueError, match="Unknown indicator 'fake'"):
            fetcher.fetch("fake", "2020", "2020", countries=["USA"])

    def test_empty_response_raises_download_error(self) -> None:
        from oxq.core.errors import DownloadError

        wb_response = [{"page": 1, "total": 0}, None]
        mock_resp = self._mock_urlopen(wb_response)

        with patch("oxq.data.factors.urllib.request.urlopen", return_value=mock_resp):
            fetcher = WorldBankFetcher()
            with pytest.raises(DownloadError, match="No data returned"):
                fetcher.fetch("gdp", "2020", "2020", countries=["USA"])

    def test_network_error_raises_download_error(self) -> None:
        from oxq.core.errors import DownloadError

        with patch(
            "oxq.data.factors.urllib.request.urlopen",
            side_effect=ConnectionError("timeout"),
        ):
            fetcher = WorldBankFetcher()
            with pytest.raises(DownloadError, match="Failed to download"):
                fetcher.fetch("gdp", "2020", "2020", countries=["USA"])


# ---------------------------------------------------------------------------
# FactorDownloader
# ---------------------------------------------------------------------------


class TestFactorDownloader:
    def test_download_creates_parquet(self, tmp_path: Path) -> None:
        df = pd.DataFrame(
            {"USA": [21.3e12], "CHN": [14.7e12]},
            index=pd.Index([2020], name="year"),
        )

        class StubFetcher:
            def fetch(self, target: str, start: str, end: str, **kwargs: object) -> pd.DataFrame:
                return df

            def list_indicators(self) -> list[str]:
                return ["gdp"]

        dl = FactorDownloader(StubFetcher(), sub="macro")
        path = dl.download("gdp", "2020", "2020", dest_dir=tmp_path)
        assert path == tmp_path / "macro" / "gdp.parquet"
        assert path.exists()

    def test_download_merges_with_existing(self, tmp_path: Path) -> None:
        sub_dir = tmp_path / "macro"
        sub_dir.mkdir(parents=True)
        existing = pd.DataFrame(
            {"USA": [21.3e12]}, index=pd.Index([2020], name="year"),
        )
        existing.to_parquet(sub_dir / "gdp.parquet")

        new_data = pd.DataFrame(
            {"USA": [23.3e12]}, index=pd.Index([2021], name="year"),
        )

        class StubFetcher:
            def fetch(self, target: str, start: str, end: str, **kwargs: object) -> pd.DataFrame:
                return new_data

            def list_indicators(self) -> list[str]:
                return ["gdp"]

        dl = FactorDownloader(StubFetcher(), sub="macro")
        path = dl.download("gdp", "2021", "2021", dest_dir=tmp_path)
        result = pd.read_parquet(path)
        assert list(result.index) == [2020, 2021]

    def test_list_available(self) -> None:
        class StubFetcher:
            def fetch(self, target: str, start: str, end: str, **kwargs: object) -> pd.DataFrame:
                return pd.DataFrame()

            def list_indicators(self) -> list[str]:
                return ["gdp", "cpi"]

        dl = FactorDownloader(StubFetcher(), sub="macro")
        assert dl.list_available() == ["gdp", "cpi"]

    def test_download_via_fetcher_and_downloader(self, tmp_path: Path) -> None:
        """Integration: WorldBankFetcher + FactorDownloader replaces old download flow."""
        wb_response = _make_wb_response("NY.GDP.MKTP.CD", {
            ("USA", 2020): 21.3e12,
            ("USA", 2021): 23.3e12,
            ("CHN", 2020): 14.7e12,
            ("CHN", 2021): 17.7e12,
        })
        body = json.dumps(wb_response).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None

        with patch("oxq.data.factors.urllib.request.urlopen", return_value=mock_resp):
            fetcher = WorldBankFetcher()
            dl = FactorDownloader(fetcher, sub="macro")
            path = dl.download(
                "gdp", "2020", "2021", dest_dir=tmp_path, countries=["USA", "CHN"],
            )

        assert path == tmp_path / "macro" / "gdp.parquet"
        assert path.exists()
        df = pd.read_parquet(path)
        assert list(df.index) == [2020, 2021]
        assert sorted(df.columns) == ["CHN", "USA"]

    def test_download_many(self, tmp_path: Path) -> None:
        call_log: list[str] = []

        class StubFetcher:
            def fetch(self, target: str, start: str, end: str, **kwargs: object) -> pd.DataFrame:
                call_log.append(target)
                return pd.DataFrame({"USA": [100.0]}, index=pd.Index([2020], name="year"))

            def list_indicators(self) -> list[str]:
                return ["gdp", "cpi"]

        dl = FactorDownloader(StubFetcher(), sub="macro")
        paths = dl.download_many(["gdp", "cpi"], "2020", "2020", dest_dir=tmp_path)
        assert set(paths.keys()) == {"gdp", "cpi"}
        assert all(p.exists() for p in paths.values())
        assert set(call_log) == {"gdp", "cpi"}

    def test_download_all_indicators(self, tmp_path: Path) -> None:
        """Verify all 4 indicators can be downloaded (with mocked API)."""
        for indicator, code in MACRO_INDICATOR_MAP.items():
            wb_response = _make_wb_response(code, {
                ("USA", 2023): 100.0,
                ("CHN", 2023): 200.0,
            })
            body = json.dumps(wb_response).encode()
            mock_resp = MagicMock()
            mock_resp.read.return_value = body
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None

            with patch("oxq.data.factors.urllib.request.urlopen", return_value=mock_resp):
                fetcher = WorldBankFetcher()
                dl = FactorDownloader(fetcher, sub="macro")
                path = dl.download(
                    indicator, "2023", "2023",
                    dest_dir=tmp_path, countries=["USA", "CHN"],
                )

            assert path.exists()
            assert path.name == f"{indicator}.parquet"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_alias_exists(self) -> None:
        from oxq.data.factors import WorldBankDownloader

        assert WorldBankDownloader is WorldBankFetcher

    def test_indicator_map_alias(self) -> None:
        from oxq.data.factors import INDICATOR_MAP

        assert INDICATOR_MAP is MACRO_INDICATOR_MAP


# ---------------------------------------------------------------------------
# read_factor
# ---------------------------------------------------------------------------


class TestReadFactor:
    def test_read_all(self, tmp_path: Path) -> None:
        _write_sample_factor(tmp_path, sub="macro")
        df = read_factor("gdp", data_dir=tmp_path)
        assert list(df.index) == [2020, 2021]
        assert sorted(df.columns) == ["CHN", "USA"]

    def test_filter_countries(self, tmp_path: Path) -> None:
        _write_sample_factor(tmp_path, sub="macro")
        df = read_factor("gdp", countries=["USA"], data_dir=tmp_path)
        assert list(df.columns) == ["USA"]

    def test_filter_missing_country_ignored(self, tmp_path: Path) -> None:
        _write_sample_factor(tmp_path, sub="macro")
        df = read_factor("gdp", countries=["USA", "JPN"], data_dir=tmp_path)
        assert list(df.columns) == ["USA"]

    def test_filter_year_range(self, tmp_path: Path) -> None:
        _write_sample_factor(tmp_path, sub="macro")
        df = read_factor("gdp", start_year=2021, data_dir=tmp_path)
        assert list(df.index) == [2021]

    def test_filter_end_year(self, tmp_path: Path) -> None:
        _write_sample_factor(tmp_path, sub="macro")
        df = read_factor("gdp", end_year=2020, data_dir=tmp_path)
        assert list(df.index) == [2020]

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Factor file not found"):
            read_factor("gdp", data_dir=tmp_path)

    def test_sub_parameter(self, tmp_path: Path) -> None:
        _write_sample_factor(tmp_path, sub="financial")
        df = read_factor("gdp", data_dir=tmp_path, sub="financial")
        assert list(df.index) == [2020, 2021]


# ---------------------------------------------------------------------------
# read_factor — financial data with point_in_time
# ---------------------------------------------------------------------------


class TestReadFactorFinancial:
    """Tests for read_factor with sub='financial' and point_in_time."""

    def _write_financial_parquet(self, tmp_path: Path) -> Path:
        factor_dir = tmp_path / "financial"
        factor_dir.mkdir(parents=True)
        df = pd.DataFrame(
            {
                "publish_date": pd.to_datetime(["2024-08-24", "2024-04-26"]),
                "period": ["quarterly", "quarterly"],
                "eps": [29.42, 16.16],
                "revenue": [8.69e10, 4.59e10],
            },
            index=pd.DatetimeIndex(
                ["2024-06-30", "2024-03-31"], name="report_date"
            ),
        )
        df.to_parquet(factor_dir / "600519.parquet")
        return tmp_path

    def test_read_financial_all(self, tmp_path: Path) -> None:
        data_dir = self._write_financial_parquet(tmp_path)
        df = read_factor("600519", sub="financial", data_dir=data_dir)
        assert len(df) == 2
        assert "eps" in df.columns
        assert "publish_date" in df.columns

    def test_read_financial_filter_indicators(self, tmp_path: Path) -> None:
        data_dir = self._write_financial_parquet(tmp_path)
        df = read_factor(
            "600519", sub="financial", indicators=["eps"], data_dir=data_dir
        )
        assert "eps" in df.columns
        assert "revenue" not in df.columns
        assert "publish_date" in df.columns  # metadata kept

    def test_read_financial_point_in_time(self, tmp_path: Path) -> None:
        """point_in_time=True filters by publish_date, not report_date."""
        data_dir = self._write_financial_parquet(tmp_path)
        # Q1 report published 2024-04-26, Q2 report published 2024-08-24
        # At 2024-05-01, only Q1 data should be visible
        df = read_factor(
            "600519",
            sub="financial",
            end="2024-05-01",
            point_in_time=True,
            data_dir=data_dir,
        )
        assert len(df) == 1
        assert df.index[0] == pd.Timestamp("2024-03-31")

    def test_read_financial_no_point_in_time(self, tmp_path: Path) -> None:
        """Without point_in_time, filters by report_date — gets both rows."""
        data_dir = self._write_financial_parquet(tmp_path)
        df = read_factor(
            "600519",
            sub="financial",
            end="2024-06-30",
            point_in_time=False,
            data_dir=data_dir,
        )
        assert len(df) == 2

    def test_read_macro_backward_compat(self, tmp_path: Path) -> None:
        """Old-style call with start_year/end_year still works."""
        factor_dir = tmp_path / "macro"
        factor_dir.mkdir(parents=True)
        df = pd.DataFrame(
            {"CHN": [14.7e12], "USA": [21.3e12]},
            index=pd.Index([2020], name="year"),
        )
        df.to_parquet(factor_dir / "gdp.parquet")
        result = read_factor(
            "gdp", sub="macro", start_year=2020, countries=["USA"], data_dir=tmp_path
        )
        assert list(result.columns) == ["USA"]
