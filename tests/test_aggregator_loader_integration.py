# -*- coding: utf-8 -*-
"""DataAggregator 与 Loader registry 集成测试。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.data.aggregator import DataAggregator
from src.data.loaders import FALLBACK_CHAINS, LOADER_REGISTRY
from src.data.loaders import registry as registry_module
from src.data.loaders.base import DataLoader
from src.data.loaders.registry import register
from src.data.schema import Quote
from src.data.source_citation import make_citation


class FirstLoader(DataLoader):
    name = "first_loader"
    markets = ["a_share"]

    def is_available(self) -> bool:
        return True

    def get_quote(self, symbol: str, market: str = "SH"):
        if symbol == "fail":
            return None
        return Quote(
            symbol=symbol,
            name="First",
            price=10.0,
            source=self.name,
        )


class SecondLoader(DataLoader):
    name = "second_loader"
    markets = ["a_share"]

    def is_available(self) -> bool:
        return True

    def get_quote(self, symbol: str, market: str = "SH"):
        return Quote(
            symbol=symbol,
            name="Second",
            price=20.0,
            source=self.name,
        )


@pytest.fixture(autouse=True)
def _patch_chain():
    original_chain = list(FALLBACK_CHAINS.get("a_share", []))
    original_registry = dict(LOADER_REGISTRY)
    original_registered = registry_module._registered
    register(FirstLoader)
    register(SecondLoader)
    FALLBACK_CHAINS["a_share"] = ["first_loader", "second_loader"]
    registry_module._registered = True
    yield
    FALLBACK_CHAINS["a_share"] = original_chain
    LOADER_REGISTRY.clear()
    LOADER_REGISTRY.update(original_registry)
    registry_module._registered = original_registered


def test_get_quote_uses_first_available_loader():
    agg = DataAggregator()
    q = agg.get_quote("600519", "SH")
    assert q is not None
    assert q.source == "first_loader"
    assert q.price == 10.0
    assert q.citation is not None
    assert q.citation.provider == "first_loader"


def test_get_quote_falls_back_when_first_returns_none():
    agg = DataAggregator()
    q = agg.get_quote("fail", "SH")
    assert q is not None
    assert q.source == "second_loader"


def test_get_quotes_batch_fills_missing_symbols():
    agg = DataAggregator()
    results = agg.get_quotes_batch([("600519", "SH"), ("fail", "SH")])
    by_symbol = {r.symbol: r for r in results}
    assert "600519" in by_symbol
    assert "fail" in by_symbol
    assert by_symbol["600519"].source == "first_loader"
    assert by_symbol["fail"].source == "second_loader"


def test_quote_citation_is_fresh_and_has_quality_score():
    agg = DataAggregator()
    q = agg.get_quote("600519", "SH")
    assert q is not None
    assert q.citation is not None
    assert q.citation.is_fresh
    assert 0.0 < q.citation.quality_score <= 1.0


def test_in_memory_cache_honors_ttl():
    agg = DataAggregator()
    agg._cache_ttl = timedelta(seconds=-1)  # 立即过期
    q1 = agg.get_quote("600519", "SH")
    # 修改 chain 让 first_loader 不在链中，验证 cache 未命中
    FALLBACK_CHAINS["a_share"] = ["second_loader"]
    q2 = agg.get_quote("600519", "SH")
    assert q2.source == "second_loader"
    assert q2.source != q1.source
