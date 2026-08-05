# -*- coding: utf-8 -*-
"""存储芯片（DRAM/NAND Flash）现货价格领先信号源测试。

覆盖:
  1. mock HTML 驱动 fetch() → 生成 LeadSourceSignal（类别/涨跌幅/日期/板块）
  2. 阈值过滤（默认 1.0%）
  3. 同类别多产品聚合取最大异动
  4. category 过滤（"NAND" / "commodity.DRAM4" / 未知）
  5. 网络/解析失败 → []（优雅降级）
  6. 6h TTL 缓存
  7. 全链路: 数据源 → to_leading_signals → [SPECULATION] 弱信号
"""

from __future__ import annotations

from datetime import date

import pytest

from src.data.commodity.memory_chip_source import MemoryChipLeadSource
from src.data.us_sector_transmission import (
    UsSectorTransmissionAdjuster,
    lead_signal_weak_adjust,
    to_leading_signals,
)


# 模拟 DRAMeXchange 首页 HTML（服务端直出日度现货报价表）
FAKE_HTML = """<html><body>
<p>Last Update: Aug.5 2026 18:10 (GMT+8) <a href="/PriceNotice">notice</a></p>
<table>
  <tr><td>DDR4 8Gb (1Gx8) 3200</td><td>74.00</td><td>20.40</td><td>74.00</td><td>20.40</td><td>42.112</td><td>0.00 %</td></tr>
  <tr><td>DDR4 16Gb (2Gx8) 3200</td><td>112.00</td><td>40.50</td><td>112.00</td><td>40.50</td><td>86.683</td><td>0.85 %</td></tr>
  <tr><td>DDR5 16Gb (2Gx8) 4800/5600</td><td>68.00</td><td>32.90</td><td>68.00</td><td>32.90</td><td>51.333</td><td>0.00 %</td></tr>
  <tr><td>512Gb TLC</td><td>22.00</td><td>16.00</td><td>22.00</td><td>16.00</td><td>19.250</td><td>1.69 %</td></tr>
  <tr><td>256Gb TLC</td><td>15.00</td><td>10.00</td><td>15.00</td><td>10.00</td><td>10.787</td><td>3.09 %</td></tr>
  <tr><td>ADATA</td><td>SATA 6.0 Gb/s</td><td>SU650</td><td>960 GB</td><td>242.00</td><td>242.00</td><td>242.00</td><td>36.60 %</td></tr>
</table>
</body></html>"""

# 无价格行 / 空 HTML（降级场景）
EMPTY_HTML = "<html><body><p>Maintenance</p></body></html>"
NOPRICE_HTML = "<html><body><table><tr><td>hello</td><td>world</td></tr></table></body></html>"


class TestMemoryChipLeadSource:
    def _src(self, threshold_pct: float = 1.0, monkeypatch=None) -> MemoryChipLeadSource:
        src = MemoryChipLeadSource(threshold_pct=threshold_pct)
        if monkeypatch is not None:
            monkeypatch.setattr(src, "_get_html", lambda: FAKE_HTML)
        return src

    def test_is_available(self):
        assert MemoryChipLeadSource().is_available() is True

    def test_fetch_generates_nand_signal(self, monkeypatch):
        """① mock HTML → NAND 类别产出信号（256Gb TLC +3.09% 为 NAND 最大异动）。"""
        src = self._src(threshold_pct=1.0, monkeypatch=monkeypatch)
        sig = src.fetch()
        by_cat = {s.category: s for s in sig}
        assert "commodity.NAND" in by_cat
        nand = by_cat["commodity.NAND"]
        assert nand.change_pct == pytest.approx(3.09)
        assert nand.name == "NAND Flash"
        assert "存储" in nand.target_sectors and "芯片" in nand.target_sectors
        assert nand.source == "dramexchange_spot"
        assert nand.confidence == pytest.approx(0.6)
        assert nand.as_of == date(2026, 8, 5)

    def test_fetch_threshold_filters_small_moves(self, monkeypatch):
        """默认阈值 1.0% → DRAM4(+0.85%)/DRAM5(0.0%) 被过滤，仅 NAND(+3.09%) 通过。"""
        src = self._src(threshold_pct=1.0, monkeypatch=monkeypatch)
        cats = {s.category for s in src.fetch()}
        assert cats == {"commodity.NAND"}

    def test_fetch_lower_threshold_captures_dram4(self, monkeypatch):
        """阈值 0.5% → DRAM4(+0.85%) 与 NAND(+3.09%) 同时产出。"""
        src = self._src(threshold_pct=0.5, monkeypatch=monkeypatch)
        by_cat = {s.category: s for s in src.fetch()}
        assert "commodity.DRAM4" in by_cat
        assert by_cat["commodity.DRAM4"].change_pct == pytest.approx(0.85)
        assert "commodity.NAND" in by_cat

    def test_same_key_aggregates_max_change(self, monkeypatch):
        """同类别多产品 → 聚合成单条信号，取 |change| 最大者。"""
        # 512Gb(+1.69) 与 256Gb(+3.09) 同属 NAND → 只产出 1 条 NAND，取 +3.09
        src = self._src(threshold_pct=1.0, monkeypatch=monkeypatch)
        nands = [s for s in src.fetch() if s.category == "commodity.NAND"]
        assert len(nands) == 1
        assert nands[0].change_pct == pytest.approx(3.09)

    def test_fetch_category_filter(self, monkeypatch):
        src = self._src(threshold_pct=0.5, monkeypatch=monkeypatch)
        assert [s.category for s in src.fetch("NAND")] == ["commodity.NAND"]
        assert [s.category for s in src.fetch("commodity.DRAM4")] == ["commodity.DRAM4"]
        assert src.fetch("ZZZ") == []

    def test_fetch_network_failure_degrades_to_empty(self, monkeypatch):
        """② 网络/解析失败 → 返回 []（优雅降级），不抛异常。"""

        def boom():
            raise RuntimeError("dramexchange down")

        monkeypatch.setattr(MemoryChipLeadSource, "_get_html", boom)
        assert MemoryChipLeadSource().fetch() == []

    def test_fetch_empty_html_degrades(self, monkeypatch):
        src = self._src(monkeypatch=monkeypatch)
        monkeypatch.setattr(src, "_get_html", lambda: EMPTY_HTML)
        assert src.fetch() == []

    def test_fetch_unparseable_html_degrades(self, monkeypatch):
        src = self._src(monkeypatch=monkeypatch)
        monkeypatch.setattr(src, "_get_html", lambda: NOPRICE_HTML)
        assert src.fetch() == []

    def test_cache_ttl_avoids_refetch(self, monkeypatch):
        """6h TTL 缓存：首次 fetch 后再次 fetch 不再请求网络。"""
        calls = {"n": 0}

        def fake_get():
            calls["n"] += 1
            return FAKE_HTML

        src = self._src(threshold_pct=0.5, monkeypatch=monkeypatch)
        monkeypatch.setattr(src, "_get_html", fake_get)
        assert len(src.fetch()) >= 1
        assert len(src.fetch()) >= 1
        assert calls["n"] == 1  # 缓存命中，仅一次网络请求

    def test_source_drives_pipeline_end_to_end(self, monkeypatch):
        """③ mock 现货数据 → 数据源 → to_leading_signals 全链路（[SPECULATION] 弱信号）。"""
        src = self._src(threshold_pct=0.5, monkeypatch=monkeypatch)
        tx = UsSectorTransmissionAdjuster().compute({"MU": -5.38})
        lead = to_leading_signals(tx, lead_sources=[src])
        src_leads = [s for s in lead if s.source == "lead_source"]
        assert src_leads
        nand = next(s for s in src_leads if s.us_key == "commodity.NAND")
        assert nand.direction == 1            # NAND 现货涨 → 利好
        assert nand.speculation is True       # 恒标 [SPECULATION]
        assert 0.0 <= nand.strength <= 1.0
        # 上游现货命名空间 → 窗口 14-28 天（doc 04 滞后约2周理念）
        assert nand.window_start_days == 14
        assert nand.window_end_days == 28
        # 配置驱动信号（MU）仍保留，叠加而非替换
        assert any(s.us_key == "MU" for s in lead)

    def test_weak_adjust_matches_storage_sector(self, monkeypatch):
        src = self._src(threshold_pct=0.5, monkeypatch=monkeypatch)
        tx = UsSectorTransmissionAdjuster().compute({"MU": -5.38})
        lead = to_leading_signals(tx, lead_sources=[src])
        # NAND(+)/DRAM4(+) 与 MU(-) 混合 → 幅度受限在 ±cap
        wa = lead_signal_weak_adjust(lead, ["存储"])
        assert -3.0 <= wa <= 3.0

    def test_package_export(self):
        from src.data.commodity import MemoryChipLeadSource as Exported
        assert Exported is MemoryChipLeadSource
