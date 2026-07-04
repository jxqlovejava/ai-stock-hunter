"""Tests for data source adapters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from oxq.data.adapters import MarketDataAdapter
from oxq.data.providers import FactorFetcher


class TestMarketDataAdapter:
    def test_satisfies_factor_fetcher(self) -> None:
        mock_downloader = MagicMock()
        adapter: FactorFetcher = MarketDataAdapter(mock_downloader)
        assert isinstance(adapter, FactorFetcher)

    def test_fetch_delegates_to_downloader(self, tmp_path: Path) -> None:
        mock_downloader = MagicMock()
        parquet_path = tmp_path / "AAPL.parquet"
        df = pd.DataFrame(
            {"close": [100.0]},
            index=pd.DatetimeIndex(["2024-01-02"], name="date"),
        )
        df.to_parquet(parquet_path)
        mock_downloader.download.return_value = parquet_path

        adapter = MarketDataAdapter(mock_downloader)
        result = adapter.fetch("AAPL", "2024-01-02", "2024-01-03")

        mock_downloader.download.assert_called_once_with("AAPL", "2024-01-02", "2024-01-03")
        assert "close" in result.columns

    def test_list_indicators_empty(self) -> None:
        adapter = MarketDataAdapter(MagicMock())
        assert adapter.list_indicators() == []
