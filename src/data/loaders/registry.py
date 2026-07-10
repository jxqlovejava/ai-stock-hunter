# -*- coding: utf-8 -*-
"""Loader 注册表与 fallback chain。

借鉴 Vibe-Trading backtest.loaders.registry，但按 ai-stock-hunter 护栏要求
返回 SourceCitation。
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import Any, Type

from src.data.loaders.base import DataLoader, NoAvailableSourceError

logger = logging.getLogger(__name__)

LOADER_REGISTRY: dict[str, Type[DataLoader]] = {}

# 市场级 fallback 链：免费源优先，付费源(有日限额)仅作兜底。
# 腾讯(免费不封IP) > mootdx(TCP行情免费) > AKShare(爬虫免费) > 华泰(HT_APIKEY) > 国信(GS_API_KEY)
FALLBACK_CHAINS: dict[str, list[str]] = {
    "a_share": ["verified_cache", "tencent", "mootdx", "akshare", "huatai", "guosen"],
    # 财务数据：mootdx/tencent 优先（快速失败），akshare 放后面（代理超时风险）
    "a_share_financials": ["verified_cache", "mootdx", "tencent", "akshare", "huatai", "guosen"],
    "us_equity": ["yahoo", "stooq", "akshare"],
    "hk_equity": ["eastmoney", "yahoo", "akshare"],
}

# 会话级可用性缓存：避免对同一不可用源反复探测
_availability_cache: dict[str, tuple[bool, float]] = {}
_AVAIL_CACHE_TTL: float = 300.0  # 5 分钟内不重复探测

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
        "src.data.loaders.huatai_loader",
        "src.data.loaders.guosen_loader",
        "src.data.loaders.tencent_loader",
        "src.data.loaders.mootdx_loader",
        "src.data.loaders.akshare_loader",
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
        # 会话级可用性缓存：避免重复探测不可用源
        cached = _availability_cache.get(name)
        if cached is not None:
            avail, ts = cached
            if time.time() - ts < _AVAIL_CACHE_TTL:
                if not avail:
                    continue  # 上次探测不可用，跳过
                # avail=True 仍需实例化（缓存只记"不可用"）
        loader_cls = LOADER_REGISTRY.get(name)
        if loader_cls is None:
            continue
        try:
            loader = loader_cls()
        except Exception as exc:
            logger.debug("loader %s failed to construct: %s", name, exc)
            _availability_cache[name] = (False, time.time())
            continue
        if loader.is_available():
            logger.debug("resolved loader for %s: %s", market, name)
            return loader
        else:
            _availability_cache[name] = (False, time.time())

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
