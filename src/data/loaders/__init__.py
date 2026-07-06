# -*- coding: utf-8 -*-
"""数据源 Loader 包。"""

from src.data.loaders.base import DataLoader, NoAvailableSourceError
from src.data.loaders.registry import (
    FALLBACK_CHAINS,
    LOADER_REGISTRY,
    VALID_SOURCES,
    get_loader_cls_with_fallback,
    list_loaders,
    register,
    resolve_loader,
)

__all__ = [
    "DataLoader",
    "NoAvailableSourceError",
    "register",
    "LOADER_REGISTRY",
    "FALLBACK_CHAINS",
    "VALID_SOURCES",
    "resolve_loader",
    "get_loader_cls_with_fallback",
    "list_loaders",
]
