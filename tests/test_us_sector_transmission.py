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
    TransmissionResult,
    UsSectorTransmissionAdjuster,
    build_lead_lag_window,
    lead_signal_weak_adjust,
    resolve_lead_lag_window,
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
