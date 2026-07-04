from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class MarketDataProvider(Protocol):
    """Market data interface: the only entry point for strategy to access market data."""

    def get_bars(self, symbol: str, start: str, end: str) -> pd.DataFrame: ...

    def get_latest(self, symbol: str) -> pd.Series: ...


@runtime_checkable
class Downloader(Protocol):
    """Data download protocol: fetch from external source and persist."""

    def download(
        self,
        symbol: str,
        start: str,
        end: str,
        dest_dir: Path | None = None,
    ) -> Path: ...

    def download_many(
        self,
        symbols: list[str],
        start: str,
        end: str,
        dest_dir: Path | None = None,
    ) -> dict[str, Path]: ...


@runtime_checkable
class FactorFetcher(Protocol):
    """Unified factor data source interface.

    Each data source (WorldBank, EastMoney, yfinance) implements one Fetcher.
    Swapping data sources only requires implementing this interface.
    """

    def fetch(
        self,
        target: str,
        start: str,
        end: str,
        **kwargs: Any,
    ) -> pd.DataFrame: ...

    def list_indicators(self) -> list[str]: ...
