# -*- coding: utf-8 -*-
"""Loader 注册表与 fallback chain。

借鉴 Vibe-Trading backtest.loaders.registry，但按 ai-stock-hunter 护栏要求
返回 SourceCitation。
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Type

from src.data.loaders.base import DataLoader, NoAvailableSourceError

logger = logging.getLogger(__name__)

LOADER_REGISTRY: dict[str, Type[DataLoader]] = {}

# 市场级 fallback 链：按数据源优先级与被封风险排序。
# 已核实缓存最高；国信官方 API 次之；mootdx+腾讯不封 IP；AKShare 作为降级。
FALLBACK_CHAINS: dict[str, list[str]] = {
    "a_share": ["verified_cache", "guosen", "mootdx", "akshare", "tencent"],
    "us_equity": ["yahoo", "stooq", "akshare"],
    "hk_equity": ["eastmoney", "yahoo", "akshare"],
}

VALID_SOURCES: set[str] = set(FALLBACK_CHAINS.get("a_share", [])) | {"local", "auto"}

# 显式本地源永不回退到网络
_NO_NETWORK_FALLBACK_SOURCES: frozenset[str] = frozenset({"verified_cache", "local"})

_registered: bool = False


def register(cls: Type[DataLoader]) -> Type[DataLoader]:
    """类装饰器：将 DataLoader 子类注册到全局注册表。"""
    LOADER_REGISTRY[cls.name] = cls
    return cls


def _ensure_registered() -> None:
    """懒加载所有 loader 模块，确保注册表被填充。"""
    global _registered
    if _registered:
        return
    _registered = True

    modules = [
        "src.data.loaders.cache_loader",
        "src.data.loaders.guosen_loader",
        "src.data.loaders.mootdx_loader",
        "src.data.loaders.akshare_loader",
        "src.data.loaders.tencent_loader",
    ]
    for mod_name in modules:
        try:
            importlib.import_module(mod_name)
        except Exception as exc:
            logger.debug("loader module %s import failed: %s", mod_name, exc)


def resolve_loader(market: str) -> DataLoader:
    """按市场 fallback 链返回第一个可用的 loader 实例。"""
    _ensure_registered()
    chain = FALLBACK_CHAINS.get(market, [])
    if not chain:
        raise NoAvailableSourceError(f"Unknown market: {market}")

    tried: list[str] = []
    for name in chain:
        tried.append(name)
        loader_cls = LOADER_REGISTRY.get(name)
        if loader_cls is None:
            continue
        try:
            loader = loader_cls()
        except Exception as exc:
            logger.debug("loader %s failed to construct: %s", name, exc)
            continue
        if loader.is_available():
            logger.debug("resolved loader for %s: %s", market, name)
            return loader

    raise NoAvailableSourceError(
        f"No available loader for {market}; tried: {tried}"
    )


def get_loader_cls_with_fallback(source: str) -> Type[DataLoader]:
    """返回指定 source 的 loader 类；不可用时按市场 fallback。

    如果 source 是本地源（verified_cache/local），禁用网络回退。
    """
    _ensure_registered()
    if source not in LOADER_REGISTRY:
        raise NoAvailableSourceError(f"Unknown data source: {source}")

    loader_cls = LOADER_REGISTRY[source]
    try:
        instance = loader_cls()
    except Exception as exc:
        logger.debug("loader %s failed to construct: %s", source, exc)
        instance = None

    if instance is not None and instance.is_available():
        return loader_cls

    if source in _NO_NETWORK_FALLBACK_SOURCES:
        raise NoAvailableSourceError(
            f"Data source '{source}' is unavailable and does not fall back to network."
        )

    for market in loader_cls.markets:
        try:
            fallback = resolve_loader(market)
            logger.warning(
                "source %s unavailable; falling back to %s for %s",
                source, fallback.name, market,
            )
            return type(fallback)
        except NoAvailableSourceError:
            continue

    raise NoAvailableSourceError(f"No fallback available for source: {source}")


def list_loaders() -> dict[str, Type[DataLoader]]:
    """返回当前已注册 loader 的只读视图。"""
    _ensure_registered()
    return dict(LOADER_REGISTRY)
