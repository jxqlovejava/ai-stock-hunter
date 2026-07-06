# -*- coding: utf-8 -*-
"""Loader registry 单元测试。"""

from __future__ import annotations

import pytest

from src.data.loaders import (
    FALLBACK_CHAINS,
    LOADER_REGISTRY,
    NoAvailableSourceError,
    get_loader_cls_with_fallback,
    list_loaders,
    register,
    resolve_loader,
)
from src.data.loaders import registry as registry_module
from src.data.loaders.base import DataLoader


class DummyLoader(DataLoader):
    name = "dummy_loader"
    markets = ["test_market"]

    def __init__(self, available: bool = True):
        self._available = available

    def is_available(self) -> bool:
        return self._available


class AnotherDummyLoader(DataLoader):
    name = "another_dummy"
    markets = ["test_market"]

    def is_available(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个测试前注册 dummy loader，测试后清理。"""
    original = dict(LOADER_REGISTRY)
    original_chain = dict(FALLBACK_CHAINS)
    original_registered = registry_module._registered
    register(DummyLoader)
    register(AnotherDummyLoader)
    FALLBACK_CHAINS["test_market"] = ["dummy_loader", "another_dummy"]
    registry_module._registered = True
    yield
    LOADER_REGISTRY.clear()
    LOADER_REGISTRY.update(original)
    FALLBACK_CHAINS.clear()
    FALLBACK_CHAINS.update(original_chain)
    registry_module._registered = original_registered


def test_register_adds_loader():
    assert "dummy_loader" in LOADER_REGISTRY
    assert LOADER_REGISTRY["dummy_loader"] is DummyLoader


def test_list_loaders_returns_registered():
    loaders = list_loaders()
    assert "dummy_loader" in loaders
    assert "another_dummy" in loaders


def test_resolve_loader_returns_first_available():
    loader = resolve_loader("test_market")
    assert loader.name == "dummy_loader"


def test_resolve_loader_skips_unavailable():
    original = DummyLoader.is_available
    DummyLoader.is_available = lambda self: False  # type: ignore[assignment]
    try:
        loader = resolve_loader("test_market")
        assert loader.name == "another_dummy"
    finally:
        DummyLoader.is_available = original  # type: ignore[assignment]


def test_resolve_loader_raises_when_none_available():
    FALLBACK_CHAINS["empty_market"] = ["dummy_loader"]
    original = DummyLoader.is_available
    DummyLoader.is_available = lambda self: False  # type: ignore[assignment]
    try:
        with pytest.raises(NoAvailableSourceError):
            resolve_loader("empty_market")
    finally:
        DummyLoader.is_available = original  # type: ignore[assignment]


def test_get_loader_cls_with_fallback_returns_requested():
    cls = get_loader_cls_with_fallback("dummy_loader")
    assert cls is DummyLoader


def test_get_loader_cls_with_fallback_falls_back():
    original = DummyLoader.is_available
    DummyLoader.is_available = lambda self: False  # type: ignore[assignment]
    try:
        cls = get_loader_cls_with_fallback("dummy_loader")
        assert cls is AnotherDummyLoader
    finally:
        DummyLoader.is_available = original  # type: ignore[assignment]


def test_local_source_no_network_fallback():
    class LocalLoader(DataLoader):
        name = "local"
        markets = ["test_market"]

        def is_available(self) -> bool:
            return False

    register(LocalLoader)
    FALLBACK_CHAINS["test_market"] = ["local", "another_dummy"]
    with pytest.raises(NoAvailableSourceError):
        get_loader_cls_with_fallback("local")
