# -*- coding: utf-8 -*-
"""P3-2 跨市场传导时间差建模测试。

覆盖:
  1. 领先/滞后窗口建模（无配置默认当日传导、显式窗口、分段时滞推导、round-trip）
  2. 分段时滞（上游现货 → 海外龙头 → A股对标 不同窗口/信号强度）
  3. compute() 向后兼容（无配置时当日传导行为不变）+ 新字段富集
  4. diagnosis._score_macro 消费领先弱信号（[SPECULATION]）
"""

from __future__ import annotations

from datetime import date

import pytest

from src.data.us_sector_transmission import (
    LeadLagStage,
    LeadLagWindow,
    LeadSignalSource,
    LeadSourceSignal,
    TransmissionResult,
    UsSectorTransmissionAdjuster,
    build_lead_lag_window,
    build_lead_signals,
    clear_lead_signal_sources,
    get_lead_signal_sources,
    lead_signal_weak_adjust,
    register_lead_signal_source,
    resolve_lead_lag_window,
    source_signal_to_lead,
    to_leading_signals,
)
from src.routing.diagnosis import DiagnosisEngine


# ─────────────────────────────────────────────────────────────
# 1. 领先/滞后窗口建模
# ─────────────────────────────────────────────────────────────
class TestLeadLagWindowModeling:
    def test_default_window_is_same_day(self):
        w = build_lead_lag_window(None)
        assert w.is_same_day
        assert (w.lag_min_days, w.lag_max_days) == (0, 0)
        # 空 dict 同样回退当日
        assert build_lead_lag_window({}).is_same_day

    def test_explicit_lag_days(self):
        w = build_lead_lag_window({"lag_days": [14, 28], "decay_per_week": 0.3})
        assert (w.lag_min_days, w.lag_max_days) == (14, 28)
        assert not w.is_same_day
        assert w.decay_per_week == pytest.approx(0.3)

    def test_explicit_lag_days_inverted_is_clamped(self):
        # min > max 时被规整为 [max, max]，保证窗口合法
        w = build_lead_lag_window({"lag_days": [28, 14]})
        assert w.lag_max_days >= w.lag_min_days

    def test_staged_config_derives_window(self):
        # 无显式 lag_days，由分段时滞总和推导窗口
        config = {
            "stages": [
                {"name": "上游现货异动", "lag_days": 4, "signal_strength": 0.9},
                {"name": "海外龙头", "lag_days": 10, "signal_strength": 0.8},
                {"name": "A股对标", "lag_days": 6, "signal_strength": 0.9},
            ],
        }
        w = build_lead_lag_window(config)
        total = 20  # 4 + 10 + 6
        assert w.lag_min_days == round(total * 0.85)
        assert w.lag_max_days == round(total * 1.25)
        assert len(w.stages) == 3

    def test_resolve_from_mapping(self):
        from src.data.us_sector_transmission import SECTOR_MAP

        mu = next(m for m in SECTOR_MAP if m["us_key"] == "MU")
        nvda = next(m for m in SECTOR_MAP if m["us_key"] == "NVDA")
        sox = next(m for m in SECTOR_MAP if m["us_key"] == "SOX")
        assert (resolve_lead_lag_window(mu).lag_min_days,
                resolve_lead_lag_window(mu).lag_max_days) == (14, 28)
        assert (resolve_lead_lag_window(nvda).lag_min_days,
                resolve_lead_lag_window(nvda).lag_max_days) == (7, 14)
        # 无 lead_lag 配置 → 当日窗口（向后兼容）
        assert resolve_lead_lag_window(sox).is_same_day

    def test_roundtrip_to_dict(self):
        w = build_lead_lag_window({
            "lag_days": [14, 28],
            "stages": [
                {"name": "上游现货异动", "lag_days": 4, "signal_strength": 0.9},
                {"name": "海外龙头", "lag_days": 10, "signal_strength": 0.8},
                {"name": "A股对标", "lag_days": 6, "signal_strength": 0.9},
            ],
        })
        w2 = build_lead_lag_window(w.to_dict())
        assert w == w2
        assert w.to_dict()["is_same_day"] is False


# ─────────────────────────────────────────────────────────────
# 2. 分段时滞（上游 → 海外 → A股 不同窗口）
# ─────────────────────────────────────────────────────────────
class TestSegmentedTimeLag:
    def test_staged_decay_product(self):
        stages = (
            LeadLagStage("上游现货异动", 4, 0.9),
            LeadLagStage("海外龙头", 10, 0.8),
            LeadLagStage("A股对标", 6, 0.9),
        )
        w = LeadLagWindow(14, 28, stages=stages)
        assert w.staged_decay == pytest.approx(0.9 * 0.8 * 0.9)  # 0.648

    def test_staged_decay_default_is_one(self):
        w = LeadLagWindow(0, 0)
        assert w.staged_decay == 1.0

    def test_lead_signal_window_matches_stages(self):
        # 构造一个上游/海外/A股 三段时滞信号，投影窗口应等于各段滞后
        tx = TransmissionResult(active_signals=[{
            "us_key": "MU",
            "us_label": "美光科技",
            "change_pct": -5.38,
            "raw_adjust": -1.94,
            "sectors": ["存储"],
            "lead_lag_window": build_lead_lag_window({
                "lag_days": [14, 28],
                "stages": [
                    {"name": "上游现货异动", "lag_days": 4, "signal_strength": 0.9},
                    {"name": "海外龙头", "lag_days": 10, "signal_strength": 0.8},
                    {"name": "A股对标", "lag_days": 6, "signal_strength": 0.9},
                ],
            }).to_dict(),
        }])
        lead = to_leading_signals(tx, as_of=date(2026, 8, 5))
        assert len(lead) == 1
        sig = lead[0]
        assert sig.window_start_days == 14
        assert sig.window_end_days == 28
        assert sig.window_start == date(2026, 8, 19)
        assert sig.window_end == date(2026, 9, 2)
        assert sig.direction == -1
        assert sig.speculation is True

    def test_lead_signal_strength_combines_decays(self):
        tx = TransmissionResult(active_signals=[{
            "us_key": "MU", "us_label": "美光科技",
            "change_pct": -5.38, "raw_adjust": -10.0, "sectors": ["存储"],
            "lead_lag_window": build_lead_lag_window({
                "lag_days": [14, 28],
                "stages": [
                    {"name": "上游现货异动", "lag_days": 4, "signal_strength": 0.9},
                    {"name": "海外龙头", "lag_days": 10, "signal_strength": 0.8},
                    {"name": "A股对标", "lag_days": 6, "signal_strength": 0.9},
                ],
            }).to_dict(),
        }])
        sig = to_leading_signals(tx)[0]
        # strength = min(1, |raw|/10)=1.0 × staged_decay=0.648 × 周衰减
        time_decay = 1.0 / (1.0 + 0.30 * (21.0 / 7.0))
        assert sig.strength == pytest.approx(0.648 * time_decay, abs=1e-3)
        assert 0.0 <= sig.strength <= 1.0

    def test_lead_signal_skipped_beyond_horizon(self):
        tx = TransmissionResult(active_signals=[{
            "us_key": "X", "us_label": "X", "raw_adjust": -5.0,
            "sectors": ["存储"],
            "lead_lag_window": {"lag_min_days": 30, "lag_max_days": 40},
        }])
        assert to_leading_signals(tx, horizon_days=20) == []

    def test_lead_signal_window_clipped_to_horizon(self):
        tx = TransmissionResult(active_signals=[{
            "us_key": "X", "us_label": "X", "raw_adjust": -5.0,
            "sectors": ["存储"],
            "lead_lag_window": {"lag_min_days": 14, "lag_max_days": 28},
        }])
        sig = to_leading_signals(tx, horizon_days=20)[0]
        assert sig.window_end_days == 20


# ─────────────────────────────────────────────────────────────
# 3. compute() 向后兼容 + 新字段富集
# ─────────────────────────────────────────────────────────────
class TestComputeBackwardCompat:
    def test_no_config_keeps_same_day_behavior(self):
        adj = UsSectorTransmissionAdjuster()
        r = adj.compute({"SOX": -3.33})  # SOX 无 lead_lag 配置
        assert r.data_available
        # 当日传导修正值不变: raw_adjust = round(chg × coeff × weight, 2)
        assert r.active_signals[0]["raw_adjust"] == pytest.approx(round(-3.33 * 0.50 * 1.0, 2))
        # 新富集字段仍为当日窗口
        assert r.active_signals[0]["lead_lag_window"]["is_same_day"] is True
        # 原有消费字段（sentinel 依赖）保持
        assert "us_label" in r.active_signals[0]
        assert "change_pct" in r.active_signals[0]

    def test_lead_lag_enriched_on_active_signal(self):
        r = UsSectorTransmissionAdjuster().compute({"MU": -5.38})
        sig = next(s for s in r.active_signals if s["us_key"] == "MU")
        assert sig["lead_lag_window"]["lag_min_days"] == 14
        assert sig["lead_lag_window"]["lag_max_days"] == 28
        assert "sectors" in sig and "存储" in sig["sectors"]

    def test_to_leading_signals_direction_and_strength(self):
        r = UsSectorTransmissionAdjuster().compute({"NVDA": 3.0, "MU": -5.38})
        lead = to_leading_signals(r, horizon_days=45)
        assert len(lead) > 0
        by_key = {s.us_key: s for s in lead}
        assert by_key["NVDA"].direction == 1      # 上涨 → 利好
        assert by_key["MU"].direction == -1       # 下跌 → 利空
        for s in lead:
            assert 0.0 <= s.strength <= 1.0
            assert s.speculation is True

    def test_weak_adjust_matches_sector(self):
        r = UsSectorTransmissionAdjuster().compute({"NVDA": 3.0, "MU": -5.38})
        lead = to_leading_signals(r, horizon_days=45)
        # 存储板块应收到 MU 的空头弱信号
        wa_storage = lead_signal_weak_adjust(lead, ["存储"])
        assert wa_storage < 0
        # 互联网板块不匹配 → 0
        assert lead_signal_weak_adjust(lead, ["互联网"]) == 0.0
        # 空候选 → 0
        assert lead_signal_weak_adjust(lead, []) == 0.0

    def test_weak_adjust_capped(self):
        # 多个强信号求和超过 cap → 被限幅在 ±cap
        tx = TransmissionResult(active_signals=[
            {
                "us_key": "X", "us_label": "X", "raw_adjust": 10.0,
                "sectors": ["存储"],
                "lead_lag_window": {"lag_min_days": 7, "lag_max_days": 14},
            },
            {
                "us_key": "Y", "us_label": "Y", "raw_adjust": 10.0,
                "sectors": ["存储"],
                "lead_lag_window": {"lag_min_days": 7, "lag_max_days": 14},
            },
            {
                "us_key": "Z", "us_label": "Z", "raw_adjust": 10.0,
                "sectors": ["存储"],
                "lead_lag_window": {"lag_min_days": 7, "lag_max_days": 14},
            },
        ])
        wa = lead_signal_weak_adjust(to_leading_signals(tx), ["存储"], cap=3.0)
        assert -3.0 <= wa <= 3.0
        # 默认 cap=3，三个强度≈1 的信号应打满上限
        assert wa == pytest.approx(3.0)


# ─────────────────────────────────────────────────────────────
# 4. diagnosis._score_macro 消费领先弱信号
# ─────────────────────────────────────────────────────────────
class TestDiagnosisLeadSignalConsumption:
    def _baseline(self) -> float:
        return DiagnosisEngine()._score_macro({})

    def test_score_macro_consumes_lead_adjust(self):
        engine = DiagnosisEngine()
        base = engine._score_macro({})
        macro = {
            "us_sector_transmission": {
                "macro_adjust": 0,
                "lead_signal_adjust": 2.0,
            }
        }
        assert engine._score_macro(macro) == pytest.approx(base + 2.0)

    def test_score_macro_ignores_missing_lead(self):
        engine = DiagnosisEngine()
        base = engine._score_macro({})
        macro = {"us_sector_transmission": {"macro_adjust": -5}}
        # 只有当日直接传导，无 lead 字段 → 不加分
        assert engine._score_macro(macro) == pytest.approx(base - 5)

    def test_score_macro_clamps_to_100(self):
        engine = DiagnosisEngine()
        macro = {
            "us_sector_transmission": {
                "macro_adjust": 0,
                "lead_signal_adjust": 90.0,  # 即使异常大也被外层 clamp
            }
        }
        score = engine._score_macro(macro)
        assert 0 <= score <= 100

    def test_score_macro_no_transmission_block(self):
        engine = DiagnosisEngine()
        assert engine._score_macro({}) == pytest.approx(self._baseline())


# ─────────────────────────────────────────────────────────────
# 5. 可插拔真实数据源（LeadSignalSource）— 跨市场传导时差接真实数据
# ─────────────────────────────────────────────────────────────
class _MockLeadSource(LeadSignalSource):
    """测试用数据源：可配置返回值 / 抛异常。"""

    name = "mock_source"

    def __init__(self, signals=None, error: Exception | None = None):
        self.signals = signals or []
        self.error = error
        self.calls = 0

    def fetch(self, category: str = "") -> list:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.signals


class TestPluggableLeadSource:
    def _upstream_signal(self, change_pct=5.0, category="commodity.CU",
                         sectors=("铜", "有色金属")):
        return LeadSourceSignal(
            category=category,
            name="沪铜",
            change_pct=change_pct,
            as_of=date(2026, 8, 5),
            source="mock",
            target_sectors=sectors,
            confidence=0.6,
        )

    def test_interface_generates_lead_signal_from_source(self):
        """① mock fetch 返回现货异动 → 断言生成领先信号（[SPECULATION] 弱信号）。"""
        tx = UsSectorTransmissionAdjuster().compute({"SOX": -3.33})
        src = _MockLeadSource(signals=[self._upstream_signal(change_pct=5.0)])
        lead = to_leading_signals(tx, lead_sources=[src])
        assert src.calls == 1
        source_leads = [s for s in lead if s.source == "lead_source"]
        assert len(source_leads) >= 1
        cu = next(s for s in source_leads if s.sector == "铜")
        assert cu.us_key == "commodity.CU"
        assert cu.direction == 1          # 现货涨 → 利好
        assert cu.speculation is True     # 恒标 [SPECULATION]
        assert 0.0 <= cu.strength <= 1.0
        # 上游现货命名空间 → 窗口 14-28 天
        assert cu.window_start_days == 14
        assert cu.window_end_days == 28
        # 配置驱动信号仍然保留（叠加而非替换）
        assert any(s.source == "us_sector_transmission_leadlag" for s in lead)

    def test_source_signal_strength_and_amplitude_limited(self):
        """幅度受限: 极端异动被限幅到 ±SOURCE_MAX_CHANGE。"""
        tx = UsSectorTransmissionAdjuster().compute({"SOX": -3.33})
        big = self._upstream_signal(change_pct=40.0)
        src = _MockLeadSource(signals=[big])
        lead = to_leading_signals(tx, lead_sources=[src])
        cu = next(s for s in lead if s.sector == "铜")
        assert abs(cu.raw_adjust) <= 8.0        # 限幅
        assert 0.0 <= cu.strength <= 1.0

    def test_fetch_failure_degrades_gracefully(self):
        """② fetch 抛异常 → 优雅降级到配置驱动路径，不抛异常、不阻塞。"""
        tx = UsSectorTransmissionAdjuster().compute({"MU": -5.38})
        src = _MockLeadSource(error=RuntimeError("network down"))
        lead = to_leading_signals(tx, lead_sources=[src])   # 不应抛异常
        # 配置驱动信号仍在
        assert any(s.us_key == "MU" for s in lead)
        assert src.calls == 1

    def test_fetch_empty_returns_config_only(self):
        """fetch 返回 [] → 无新增信号，与无数据源时一致。"""
        tx = UsSectorTransmissionAdjuster().compute({"MU": -5.38})
        baseline = to_leading_signals(tx)
        lead = to_leading_signals(tx, lead_sources=[_MockLeadSource(signals=[])])
        assert lead == baseline

    def test_enhances_existing_signal_sector(self):
        """③ 与既有 to_leading_signals 集成: 现货异动增强同一板块信号。"""
        tx = UsSectorTransmissionAdjuster().compute({"MU": -5.38})
        # 碳酸锂现货上涨 → 新能源车/锂电 板块领先信号（新增维度）
        src = _MockLeadSource(signals=[
            LeadSourceSignal(
                category="commodity.LC", name="碳酸锂", change_pct=4.0,
                source="mock", target_sectors=("锂电", "新能源车"), confidence=0.6,
            )
        ])
        lead = to_leading_signals(tx, lead_sources=[src], horizon_days=45)
        assert any(s.us_key == "commodity.LC" and s.sector == "锂电" for s in lead)
        # 存储板块仍收到 MU 空头弱信号
        assert lead_signal_weak_adjust(lead, ["存储"]) < 0
        # 锂电板块收到碳酸锂上涨利好
        assert lead_signal_weak_adjust(lead, ["锂电"]) > 0

    def test_source_signals_capped_in_weak_adjust(self):
        """多源信号求和仍被 lead_signal_weak_adjust 限幅在 ±cap。"""
        tx = UsSectorTransmissionAdjuster().compute({"SOX": -3.33})
        many = [_MockLeadSource(signals=[self._upstream_signal(change_pct=9.0, sectors=("铜",))])
                for _ in range(5)]
        lead = to_leading_signals(tx, lead_sources=many)
        wa = lead_signal_weak_adjust(lead, ["铜"], cap=3.0)
        assert -3.0 <= wa <= 3.0

    def test_build_lead_signals_convenience(self):
        """build_lead_signals 便捷入口与 to_leading_signals 等价。"""
        tx = UsSectorTransmissionAdjuster().compute({"SOX": -3.33})
        src = _MockLeadSource(signals=[self._upstream_signal(change_pct=3.0)])
        assert build_lead_signals(tx, lead_sources=[src]) == to_leading_signals(
            tx, lead_sources=[src]
        )

    def test_source_signal_to_lead_beyond_horizon_skipped(self):
        tx = UsSectorTransmissionAdjuster().compute({"SOX": -3.33})
        src = _MockLeadSource(signals=[self._upstream_signal(change_pct=3.0)])
        lead = to_leading_signals(tx, lead_sources=[src], horizon_days=10)
        # 上游现货窗口 14-28 > horizon 10 → 被跳过
        assert not any(s.source == "lead_source" for s in lead)
        # 配置驱动信号仍在
        assert any(s.us_key == "SOX" for s in lead)

    def test_source_signal_to_lead_window_dates(self):
        tx = UsSectorTransmissionAdjuster().compute({"SOX": -3.33})
        src = _MockLeadSource(signals=[self._upstream_signal(change_pct=3.0)])
        lead = to_leading_signals(tx, lead_sources=[src], as_of=date(2026, 8, 5))
        cu = next(s for s in lead if s.sector == "铜")
        assert cu.window_start == date(2026, 8, 19)
        assert cu.window_end == date(2026, 9, 2)

    def test_registry_and_env_empty_by_default(self):
        """无任何数据源配置 → 注册表为空、环境未配置 → 行为与现状一致。"""
        clear_lead_signal_sources()
        assert get_lead_signal_sources() == []
        tx = UsSectorTransmissionAdjuster().compute({"MU": -5.38})
        assert to_leading_signals(tx) == to_leading_signals(tx, lead_sources=[])

    def test_registry_registration(self, monkeypatch):
        """显式注册的数据源被 get_lead_signal_sources 返回。"""
        monkeypatch.delenv("AI_STOCK_LEAD_SOURCES", raising=False)
        clear_lead_signal_sources()
        src = _MockLeadSource(signals=[self._upstream_signal(change_pct=2.5)])
        register_lead_signal_source(src)
        assert get_lead_signal_sources() == [src]
        clear_lead_signal_sources()

    def test_env_enabled_source_loaded(self, monkeypatch):
        """环境变量 AI_STOCK_LEAD_SOURCES=futures_spot 启用真实数据源。"""
        clear_lead_signal_sources()
        monkeypatch.setenv("AI_STOCK_LEAD_SOURCES", "futures_spot")
        try:
            names = [s.name for s in get_lead_signal_sources()]
            assert "futures_spot" in names
        finally:
            clear_lead_signal_sources()


class TestFuturesSpotLeadSource:
    """真实数据源 FuturesSpotLeadSource — 用 mock 数据驱动管道验证。"""

    def _fake_df(self):
        import pandas as pd
        return pd.DataFrame([
            {"date": "20260804", "symbol": "CU", "spot_price": 100.0},
            {"date": "20260805", "symbol": "CU", "spot_price": 105.0},
            {"date": "20260804", "symbol": "AU", "spot_price": 800.0},
            {"date": "20260805", "symbol": "AU", "spot_price": 810.0},
            {"date": "20260805", "symbol": "LC", "spot_price": 100.0},  # 仅一日 → 无涨跌幅
        ])

    def test_fetch_computes_spot_change(self, monkeypatch):
        from src.data.commodity.futures_spot_source import FuturesSpotLeadSource
        monkeypatch.setattr(
            "akshare.futures_spot_price_daily",
            lambda start_day, end_day: self._fake_df(),
        )
        src = FuturesSpotLeadSource(threshold_pct=2.0)
        signals = src.fetch()
        by_cat = {s.category: s for s in signals}
        # CU 100→105 = +5% ≥2% 阈值 → 产出
        assert "commodity.CU" in by_cat
        assert by_cat["commodity.CU"].change_pct == pytest.approx(5.0)
        assert by_cat["commodity.CU"].target_sectors == ("铜", "有色金属", "电缆")
        # AU 800→810 = +1.25% < 2% → 被阈值过滤
        assert "commodity.AU" not in by_cat
        # LC 仅一日 → 无涨跌幅
        assert "commodity.LC" not in by_cat

    def test_fetch_category_filter(self, monkeypatch):
        from src.data.commodity.futures_spot_source import FuturesSpotLeadSource
        monkeypatch.setattr(
            "akshare.futures_spot_price_daily",
            lambda start_day, end_day: self._fake_df(),
        )
        src = FuturesSpotLeadSource(threshold_pct=2.0)
        assert [s.category for s in src.fetch("CU")] == ["commodity.CU"]
        assert [s.category for s in src.fetch("commodity.CU")] == ["commodity.CU"]
        assert src.fetch("ZZZ") == []

    def test_fetch_failure_degrades_to_empty(self, monkeypatch):
        """网络/解析失败 → 返回 []（优雅降级），不抛异常。"""
        from src.data.commodity.futures_spot_source import FuturesSpotLeadSource

        def boom(start_day, end_day):
            raise RuntimeError("100ppi down")

        monkeypatch.setattr("akshare.futures_spot_price_daily", boom)
        src = FuturesSpotLeadSource()
        assert src.fetch() == []

    def test_fetch_empty_df_returns_empty(self, monkeypatch):
        from src.data.commodity.futures_spot_source import FuturesSpotLeadSource
        import pandas as pd
        monkeypatch.setattr(
            "akshare.futures_spot_price_daily",
            lambda start_day, end_day: pd.DataFrame(),
        )
        assert FuturesSpotLeadSource().fetch() == []

    def test_source_drives_pipeline_end_to_end(self, monkeypatch):
        """mock 现货数据 → 数据源 → to_leading_signals 全链路。"""
        from src.data.commodity.futures_spot_source import FuturesSpotLeadSource
        monkeypatch.setattr(
            "akshare.futures_spot_price_daily",
            lambda start_day, end_day: self._fake_df(),
        )
        src = FuturesSpotLeadSource(threshold_pct=2.0)
        tx = UsSectorTransmissionAdjuster().compute({"SOX": -3.33})
        lead = to_leading_signals(tx, lead_sources=[src])
        cu = next(s for s in lead if s.us_key == "commodity.CU")
        assert cu.direction == 1
        assert cu.speculation is True
        assert cu.source == "lead_source"
