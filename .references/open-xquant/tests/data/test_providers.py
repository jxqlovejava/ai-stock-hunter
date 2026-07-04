from typing import Any

import pandas as pd

from oxq.data.providers import FactorFetcher, MarketDataProvider


class FakeProvider:
    def get_bars(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        return pd.DataFrame()

    def get_latest(self, symbol: str) -> pd.Series:
        return pd.Series()


def test_fake_provider_satisfies_protocol() -> None:
    provider: MarketDataProvider = FakeProvider()
    assert isinstance(provider, MarketDataProvider)


class TestFactorFetcherProtocol:
    def test_concrete_class_satisfies_protocol(self) -> None:
        class DummyFetcher:
            def fetch(
                self, target: str, start: str, end: str, **kwargs: Any
            ) -> pd.DataFrame:
                return pd.DataFrame()

            def list_indicators(self) -> list[str]:
                return []

        fetcher: FactorFetcher = DummyFetcher()
        assert isinstance(fetcher, FactorFetcher)

    def test_incomplete_class_fails_protocol(self) -> None:
        class IncompleteFetcher:
            def fetch(self, target: str) -> pd.DataFrame:
                return pd.DataFrame()

        assert not isinstance(IncompleteFetcher(), FactorFetcher)


class TestDownloaderReexport:
    def test_import_from_providers(self) -> None:
        from oxq.data.loaders import Downloader as LoadersDownloader
        from oxq.data.providers import Downloader as ProvidersDownloader

        assert ProvidersDownloader is LoadersDownloader
