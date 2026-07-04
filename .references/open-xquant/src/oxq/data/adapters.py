"""Adapters to bridge existing downloaders to the FactorFetcher Protocol."""

from __future__ import annotations

from typing import Any

import pandas as pd


class MarketDataAdapter:
    """Adapts YFinanceDownloader/AkShareDownloader to FactorFetcher Protocol."""

    def __init__(self, downloader: Any) -> None:
        self.downloader = downloader

    def fetch(
        self,
        target: str,
        start: str,
        end: str,
        **kwargs: Any,
    ) -> pd.DataFrame:
        path = self.downloader.download(target, start, end)
        return pd.read_parquet(path)

    def list_indicators(self) -> list[str]:
        return []
