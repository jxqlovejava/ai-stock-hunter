# -*- coding: utf-8 -*-
"""UsStockLeadSource（海外龙头 us_stock 命名空间）测试。

覆盖:
  1. mock ulist 数据 → UsStockLeadSource 产出 us_stock 命名空间领先信号
  2. fetch 失败/源不可用 → [] 优雅降级（不阻塞 lead-lag 管道）
  3. category 过滤 + 阈值过滤 + TTL 缓存 + 未知 secid 跳过
  4. 与 to_leading_signals 集成（us_stock 窗口 [7,14] 应用 + "股价"标签）
  5. _fetch_extra_us_tickers 修复（secid 前缀 + f13.f12 重建匹配）
  6. 环境变量 AI_STOCK_LEAD_SOURCES=us_stock 懒加载
"""

from __future__ import annotations

from datetime import date

import pytest

from src.data.us_sector_transmission import (
    EXTRA_US_SECIDS,
    UsSectorTransmissionAdjuster,
    _fetch_extra_us_tickers,
    clear_lead_signal_sources,
    get_lead_signal_sources,
    source_signal_to_lead,
    to_leading_signals,
)
from src.data.us_stock_lead_source import UsStockLeadSource


def _row(secid: str = "105.MU", name: str = "美光科技", chg: float = 3.0, as_of=None) -> dict:
    """构造一条 `_fetch_ulist` 返回行。"""
    m, c = secid.split(".", 1)
    return {"secid": secid, "name": name, "change_pct": chg, "as_of": as_of}


class TestUsStockLeadSourceFetch:
    """① mock ulist 数据 → 产出 us_stock 命名空间信号。"""

    def test_fetch_builds_signals(self, monkeypatch):
        src = UsStockLeadSource(threshold_pct=2.0)
        monkeypatch.setattr(src, "_fetch_ulist", lambda: [_row("105.MU", "美光科技", 3.0)])
        signals = src.fetch()
        assert len(signals) == 1
        s = signals[0]
        assert s.category == "us_stock.MU"
        assert s.name == "美光科技"
        assert s.change_pct == pytest.approx(3.0)
        assert s.target_sectors == ("存储", "芯片")
        assert s.confidence == 0.7
        assert s.source == "eastmoney_push2_us"

    def test_threshold_filters_noise(self, monkeypatch):
        src = UsStockLeadSource(threshold_pct=2.0)
        monkeypatch.setattr(src, "_fetch_ulist", lambda: [_row("105.MU", "美光科技", 1.0)])
        assert src.fetch() == []

    def test_category_filter(self, monkeypatch):
        src = UsStockLeadSource(threshold_pct=1.0)
        monkeypatch.setattr(src, "_fetch_ulist", lambda: [
            _row("105.MU", "美光科技", 3.0),
            _row("105.NVDA", "英伟达", 4.0),
        ])
        assert [s.category for s in src.fetch("MU")] == ["us_stock.MU"]
        assert [s.category for s in src.fetch("us_stock.MU")] == ["us_stock.MU"]
        assert src.fetch("ZZZ") == []
        assert len(src.fetch("")) == 2  # 空 category = 全部

    def test_unknown_secid_skipped(self, monkeypatch):
        """不在 US_STOCK_META 中的标的（如 QQQ）被跳过。"""
        src = UsStockLeadSource(threshold_pct=1.0)
        monkeypatch.setattr(src, "_fetch_ulist", lambda: [
            _row("105.MU", "美光科技", 3.0),
            _row("105.QQQ", "纳指ETF", 3.0),
        ])
        assert [s.category for s in src.fetch()] == ["us_stock.MU"]

    def test_ttl_cache(self, monkeypatch):
        """6h TTL 缓存: 第二次 fetch 不重复请求底层源。"""
        src = UsStockLeadSource(threshold_pct=1.0)
        calls = {"n": 0}

        def fake_fetch_ulist():
            calls["n"] += 1
            return [_row("105.MU", "美光科技", 3.0)]

        monkeypatch.setattr(src, "_fetch_ulist", fake_fetch_ulist)
        src.fetch()
        src.fetch()
        assert calls["n"] == 1


class TestUsStockLeadSourceDegrade:
    """② fetch 失败/源不可用 → [] 优雅降级。"""

    def test_fetch_ulist_raises_degrades(self, monkeypatch):
        src = UsStockLeadSource()

        def boom():
            raise RuntimeError("push2 down")

        monkeypatch.setattr(src, "_fetch_ulist", boom)
        assert src.fetch() == []

    def test_fetch_all_raises_degrades(self, monkeypatch):
        """内部任意异常（含缓存/构建阶段）→ fetch() 返回 [] 不抛。"""
        src = UsStockLeadSource()

        def boom():
            raise ConnectionError("refused")

        monkeypatch.setattr(src, "_fetch_all", boom)
        assert src.fetch() == []

    def test_integration_fetch_failure_keeps_config_signals(self, monkeypatch):
        """fetch 失败 → to_leading_signals 优雅降级，配置驱动信号仍在。"""
        src = UsStockLeadSource()

        def boom():
            raise ConnectionError("network down")

        monkeypatch.setattr(src, "_fetch_ulist", boom)
        tx = UsSectorTransmissionAdjuster().compute({"MU": -5.38})
        lead = to_leading_signals(tx, lead_sources=[src])  # 不抛异常
        assert any(s.us_key == "MU" for s in lead)  # 配置驱动仍在
        assert not any(s.source == "lead_source" for s in lead)


class TestUsStockLeadSourcePipeline:
    """③ 与 to_leading_signals 集成（us_stock 窗口 [7,14] + 股价标签）。"""

    def test_lead_signal_window_applied(self, monkeypatch):
        src = UsStockLeadSource(threshold_pct=1.0)
        monkeypatch.setattr(src, "_fetch_ulist", lambda: [_row("105.MU", "美光科技", -5.0)])
        tx = UsSectorTransmissionAdjuster().compute({"SOX": -3.33})
        lead = to_leading_signals(
            tx, lead_sources=[src], as_of=date(2026, 8, 5), horizon_days=30
        )
        mu = next(s for s in lead if s.us_key == "us_stock.MU")
        # us_stock 命名空间 → 海外龙头窗口 [7,14] 天
        assert mu.window_start_days == 7
        assert mu.window_end_days == 14
        assert mu.window_start == date(2026, 8, 12)
        assert mu.window_end == date(2026, 8, 19)
        assert mu.direction == -1          # 下跌 → 利空
        assert mu.speculation is True      # 恒标 [SPECULATION]
        assert mu.source == "lead_source"
        assert mu.sector == "存储"
        assert "股价" in mu.us_label        # 海外龙头用"股价"标签而非"现货"

    def test_source_signal_to_lead_direct(self, monkeypatch):
        src = UsStockLeadSource(threshold_pct=1.0)
        monkeypatch.setattr(src, "_fetch_ulist", lambda: [_row("105.MU", "美光科技", 5.0)])
        sigs = src.fetch()
        assert sigs
        lead = source_signal_to_lead(sigs[0], as_of=date(2026, 8, 5), horizon_days=30)
        assert lead[0].window_start_days == 7
        assert lead[0].window_end_days == 14
        assert "股价" in lead[0].us_label

    def test_weak_adjust_matches_sector(self, monkeypatch):
        from src.data.us_sector_transmission import lead_signal_weak_adjust

        src = UsStockLeadSource(threshold_pct=1.0)
        monkeypatch.setattr(src, "_fetch_ulist", lambda: [_row("105.MU", "美光科技", 6.0)])
        tx = UsSectorTransmissionAdjuster().compute({"SOX": -3.33})
        lead = to_leading_signals(tx, lead_sources=[src], horizon_days=30)
        # 美光上涨 → 存储板块收到利好弱信号
        assert lead_signal_weak_adjust(lead, ["存储"]) > 0
        # 互联网板块不匹配 → 0
        assert lead_signal_weak_adjust(lead, ["互联网"]) == 0.0

    def test_env_loaded_us_stock(self, monkeypatch):
        """AI_STOCK_LEAD_SOURCES=futures_spot,us_stock 懒加载两个源。"""
        clear_lead_signal_sources()
        monkeypatch.setenv("AI_STOCK_LEAD_SOURCES", "futures_spot,us_stock")
        try:
            names = [s.name for s in get_lead_signal_sources()]
            assert "us_stock" in names
            assert "futures_spot" in names
        finally:
            clear_lead_signal_sources()


class TestFetchExtraUsTickersFix:
    """⑤ _fetch_extra_us_tickers 修复验证（secid 前缀 + f13.f12 重建匹配）。"""

    def test_returns_keyed_changes(self, monkeypatch):
        import curl_cffi.requests as cr

        fake_items = [
            {"f12": "MU", "f13": "105", "f14": "美光科技", "f3": 3.15},
            {"f12": "NVDA", "f13": "105", "f14": "英伟达", "f3": 4.25},
            {"f12": "BABA", "f13": "106", "f14": "阿里巴巴", "f3": -0.37},
        ]

        class FakeResp:
            def json(self):
                return {"data": {"diff": fake_items}}

        monkeypatch.setattr(
            cr, "get", lambda url, headers, timeout, impersonate: FakeResp()
        )
        res = _fetch_extra_us_tickers(["MU", "NVDA", "BABA"])
        assert res == {"MU": 3.15, "NVDA": 4.25, "BABA": -0.37}

    def test_network_failure_returns_empty(self, monkeypatch):
        import curl_cffi.requests as cr

        def boom(url, headers, timeout, impersonate):
            raise ConnectionError("push2 down")

        monkeypatch.setattr(cr, "get", boom)
        assert _fetch_extra_us_tickers(["MU"]) == {}

    def test_extras_use_correct_market_prefix(self):
        """回归护栏: EXTRA_US_SECIDS 必须用 105/106/107/251 前缀而非 100。"""
        for key, secid in EXTRA_US_SECIDS.items():
            market = secid.split(".")[0]
            assert market in ("105", "106", "107", "251"), (
                f"{key} 前缀错误: {secid}（美股需 105/106/107，指数 251）"
            )
