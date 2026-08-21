# -*- coding: utf-8 -*-
"""当日全市场资金面数据缓存 — 龙虎榜/融资融券/北向/大宗交易跨进程复用。

背景: attribution 引擎的资金面通道每次都以新进程拉取全市场数据
(龙虎榜/融资融券/北向/大宗交易遍历数千只股票，实测 ~80s)，同一交易日内
多次归因会重复付出全市场拉取成本。

本模块提供 `daily_market_cache` 装饰器：按自然日 key 将结果 pickle 落盘到
data/cache/market/，同一交易日首个调用方拉真实数据，其后所有调用方(跨进程、
跨标的)直接读盘。空 DataFrame / None 结果不落盘，避免缓存"整天空"。
"""

from __future__ import annotations

import logging
import os
import pickle
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MARKET_CACHE_DIR = Path("data/cache/market")

# 设置该环境变量(任意非空值)可整体禁用市场磁盘缓存 —— 测试环境用，避免
# mock 场景被真实缓存污染；生产 CLI 不设置，缓存正常生效。
_ENV_DISABLE = "BAIZE_NO_MARKET_CACHE"


def daily_market_cache(
    name: str,
    cache_dir: Path | None = None,
    key_fn: Callable | None = None,
    cache_predicate: Callable | None = None,
):
    """当日数据磁盘缓存装饰器（pickle，支持任意可序列化对象）。

    Args:
        name: 缓存文件名前缀（如 "dragon_tiger"），同一天内全局唯一。
        cache_dir: 缓存目录（默认 data/cache/market）。
        key_fn: 可选，从 (*args, **kwargs) 提取子 key（如个股代码），
            用于按参数区分缓存文件。默认无子 key。
        cache_predicate: 可选，接收结果判断是否落盘。默认: 非 None 且非空
            DataFrame。返回 False 的结果不落盘 —— 避免失败/空结果被缓存整天。
            注意: 默认谓词只识别 DataFrame 的 .empty；对 list/dict 等容器，
            默认会缓存空容器 —— 若调用方返回空列表表示"无数据/失败"，
            应显式传 cache_predicate（如 lambda r: len(r) > 0）。

    Returns:
        包装后的函数：同一自然日内仅首次真正拉取，其余直接读盘。
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if os.environ.get(_ENV_DISABLE):
                return fn(*args, **kwargs)
            today = datetime.now().strftime("%Y%m%d")
            cdir = cache_dir or DEFAULT_MARKET_CACHE_DIR
            cdir.mkdir(parents=True, exist_ok=True)
            key = key_fn(*args, **kwargs) if key_fn else ""
            fname = f"{name}{('_' + str(key)) if key else ''}_{today}.pkl"
            cache_file = cdir / fname

            if cache_file.exists():
                try:
                    with open(cache_file, "rb") as fh:
                        cached = pickle.load(fh)
                    logger.info("[market_cache] 命中 %s", cache_file)
                    return cached
                except Exception as e:
                    logger.warning("[market_cache] 读取 %s 失败，重新拉取: %s", cache_file, e)

            result = fn(*args, **kwargs)

            if cache_predicate is not None:
                should_cache = cache_predicate(result)
            else:
                should_cache = result is not None and not (
                    hasattr(result, "empty") and result.empty
                )
            if should_cache:
                try:
                    with open(cache_file, "wb") as fh:
                        pickle.dump(result, fh)
                    logger.info("[market_cache] 已缓存 %d 字节 → %s", cache_file.stat().st_size, cache_file)
                except Exception as e:
                    logger.warning("[market_cache] 写入 %s 失败: %s", cache_file, e)

            return result

        return wrapper

    return decorator
