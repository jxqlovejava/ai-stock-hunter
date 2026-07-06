# -*- coding: utf-8 -*-
"""具体 Loader 单元测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.data.loaders.akshare_loader import AKShareLoader
from src.data.loaders.cache_loader import VerifiedCacheLoader
from src.data.loaders.guosen_loader import GuosenLoader
from src.data.loaders.mootdx_loader import MootdxLoader
from src.data.loaders.tencent_loader import TencentLoader


@pytest.fixture
def sample_kline_csv(tmp_path: Path):
    path = tmp_path / "000001_20150101_20251231_daily.csv"
    df = pd.DataFrame({
        "日期": ["2025-01-01", "2025-01-02"],
        "开盘": [10.0, 10.2],
        "收盘": [10.1, 10.3],
        "最高": [10.2, 10.4],
        "最低": [9.9, 10.1],
        "成交量": [1000, 2000],
        "成交额": [10000, 20000],
        "涨跌幅": [1.0, 1.98],
    })
    df.to_csv(path, index=False)
    return path


def test_cache_loader_history_returns_cited_dataframe(sample_kline_csv: Path):
    loader = VerifiedCacheLoader(cache_dir=sample_kline_csv.parent)
    df = loader.get_history("000001", "20150101", "20251231")
    assert not df.empty
    assert "source_citation" in df.attrs
    assert df.attrs["source_citation"].provider == "verified_cache"


def test_cache_loader_quote_from_last_row(sample_kline_csv: Path):
    loader = VerifiedCacheLoader(cache_dir=sample_kline_csv.parent)
    q = loader.get_quote("000001")
    assert q is not None
    assert q.symbol == "000001"
    assert q.price == 10.3
    assert q.source == "verified_cache"


@pytest.mark.parametrize("loader_cls", [MootdxLoader, TencentLoader, GuosenLoader, AKShareLoader])
def test_loader_declares_name_and_markets(loader_cls):
    assert loader_cls.name
    assert loader_cls.markets


def test_mootdx_loader_health_check_does_not_crash():
    loader = MootdxLoader()
    # 仅检查不抛异常
    loader.is_available()


def test_guosen_loader_unavailable_without_key():
    loader = GuosenLoader()
    # 无 GS_APIKEY 或环境未配置时应不可用；有 key 时 health_check 可能通过。
    # 此测试仅保证接口不抛异常。
    loader.is_available()
    loader._provider_instance()


def test_akshare_loader_health_check_does_not_crash():
    loader = AKShareLoader()
    loader.is_available()
