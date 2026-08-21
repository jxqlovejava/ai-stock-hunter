# -*- coding: utf-8 -*-
"""Test market_cache.daily_market_cache — 当日资金面数据磁盘缓存装饰器。"""

from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd
import pytest

from src.data.market_cache import daily_market_cache


class TestDailyMarketCache:
    """daily_market_cache 装饰器行为。"""

    def test_returns_result_and_caches_nonempty(self, tmp_path: Path):
        """非空结果落盘一次，第二次命中缓存不再调用。"""
        calls = []

        @daily_market_cache("t_nonempty", cache_dir=tmp_path)
        def fetch():
            calls.append(1)
            return pd.DataFrame({"a": [1, 2], "b": [3.5, 4.5]})

        r1 = fetch()
        r2 = fetch()
        assert len(r1) == 2 and len(r2) == 2
        assert calls == [1], "第二次应命中缓存，不再调用底层函数"
        files = list(tmp_path.glob("t_nonempty_*.pkl"))
        assert len(files) == 1

    def test_empty_dataframe_not_cached(self, tmp_path: Path):
        """空 DataFrame 每次真实调用，不落盘（避免缓存'整天空'）。"""
        calls = []

        @daily_market_cache("t_empty", cache_dir=tmp_path)
        def fetch():
            calls.append(1)
            return pd.DataFrame()

        assert fetch().empty
        assert fetch().empty
        assert calls == [1, 1], "空结果不缓存，应每次都调用"
        assert list(tmp_path.glob("t_empty_*.pkl")) == []

    def test_none_not_cached(self, tmp_path: Path):
        """None 结果不落盘。"""
        calls = []

        @daily_market_cache("t_none", cache_dir=tmp_path)
        def fetch():
            calls.append(1)
            return None

        assert fetch() is None
        assert calls == [1]
        assert list(tmp_path.glob("t_none_*.pkl")) == []

    def test_key_fn_partitions_by_symbol(self, tmp_path: Path):
        """key_fn 按 symbol 区分缓存文件，不同 symbol 各自拉取。"""
        calls = []

        @daily_market_cache("t_key", cache_dir=tmp_path, key_fn=lambda *a, **k: a[0])
        def fetch(symbol: str):
            calls.append(symbol)
            return pd.DataFrame({"s": [symbol]})

        fetch("000001")
        fetch("000001")
        fetch("600519")
        assert calls == ["000001", "600519"], "同 symbol 复用，不同 symbol 各自拉取"
        files = sorted(p.name for p in tmp_path.glob("t_key_*.pkl"))
        assert len(files) == 2
        assert any("000001" in f for f in files)
        assert any("600519" in f for f in files)

    def test_cache_predicate_controls_persistence(self, tmp_path: Path):
        """cache_predicate 返回 False 时不落盘。"""
        calls = []

        @daily_market_cache(
            "t_pred", cache_dir=tmp_path,
            cache_predicate=lambda r: isinstance(r, dict) and not r.get("data_gap_reason", ""),
        )
        def fetch(ok: bool):
            calls.append(ok)
            if not ok:
                return {"data_gap_reason": "[DATA_GAP] x"}
            return {"data_gap_reason": ""}

        fetch(False)  # data_gap → 不缓存
        fetch(True)   # 成功 → 缓存
        fetch(True)   # 命中
        assert calls == [False, True], "data_gap 结果不缓存；成功结果第二次命中"
        assert len(list(tmp_path.glob("t_pred_*.pkl"))) == 1

    def test_corrupt_cache_falls_back_to_fetch(self, tmp_path: Path):
        """损坏的缓存文件读失败 → 重新拉取并覆盖。"""
        calls = []

        @daily_market_cache("t_corrupt", cache_dir=tmp_path)
        def fetch():
            calls.append(1)
            return pd.DataFrame({"x": [1]})

        fetch()  # 首次生成缓存
        cache_file = next(tmp_path.glob("t_corrupt_*.pkl"))
        cache_file.write_bytes(b"not-a-valid-pickle")
        calls.clear()

        df = fetch()
        assert len(df) == 1
        assert calls == [1], "损坏缓存应触发重新拉取"
        # 重新拉取后正确落盘
        with open(cache_file, "rb") as fh:
            assert len(pickle.load(fh)) == 1

    def test_empty_list_not_cached_by_default_predicate(self, tmp_path: Path):
        """返回空 list 的调用方默认会被缓存整天 —— 需显式 predicate 拦截。

        回归: block_trade._fetch_daily_records 失败/无数据返回 []，
        若无 predicate，空列表会落盘整天，静默吞掉后续归因的大宗数据。
        """
        calls = []

        @daily_market_cache(
            "t_bt", cache_dir=tmp_path,
            cache_predicate=lambda r: len(r) > 0,
        )
        def fetch():
            calls.append(1)
            return []  # 无数据/失败

        assert fetch() == []
        assert fetch() == []
        assert calls == [1, 1], "空列表不应缓存，应每次都调用"
        assert list(tmp_path.glob("t_bt_*.pkl")) == []

    def test_cache_isolated_by_date(self, tmp_path: Path):
        """缓存文件名含日期，跨日自动隔离（新一天重新拉取）。"""
        @daily_market_cache("t_date", cache_dir=tmp_path)
        def fetch():
            return pd.DataFrame({"x": [1]})

        fetch()
        names = [p.name for p in tmp_path.glob("t_date_*.pkl")]
        assert len(names) == 1
        assert "20" in names[0], "文件名应包含日期"
