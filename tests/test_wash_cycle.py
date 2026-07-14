# -*- coding: utf-8 -*-
"""多波洗盘生命周期 + 与既有 washout 形态去重集成测试。"""

from __future__ import annotations

from src.game_theory.manipulation.wash_cycle import (
    WashCycleAnalyzer,
    WashCyclePhase,
)
from src.game_theory.manipulation.washout_detector import WashoutDetector
from src.game_theory.manipulation.sizing import ManipulationSizingEngine
from src.game_theory.playbooks import TOP_PLAYBOOKS


def _bars_decline(
    n: int = 12,
    start: float = 100.0,
    daily_drop: float = 0.015,
    vol_start: float = 1_000_000,
    vol_decay: float = 0.92,
    bounce_at: int | None = None,
    bounce_pct: float = 0.03,
) -> list[dict]:
    """构造偏弱日线；可选在 bounce_at 日插入弱反弹。"""
    bars: list[dict] = []
    price = start
    vol = vol_start
    for i in range(n):
        if bounce_at is not None and i == bounce_at:
            o = price
            c = price * (1 + bounce_pct)
            h = c * 1.002
            l = o * 0.998
            price = c
        else:
            o = price
            c = price * (1 - daily_drop)
            h = o * 1.001
            l = c * 0.999
            price = c
        bars.append(
            {
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
                "date": f"2026-06-{i + 1:02d}",
            }
        )
        vol *= vol_decay
    return bars


class TestWashCycleAnalyzer:
    def test_quiet_on_insufficient_decline(self):
        bars = _bars_decline(n=10, daily_drop=0.002)
        # tiny drops may still form a weak decline; force flat
        for b in bars:
            b["close"] = 100.0
            b["open"] = 100.0
            b["high"] = 100.5
            b["low"] = 99.5
        r = WashCycleAnalyzer().analyze("000001", bars)
        assert r.phase == WashCyclePhase.QUIET

    def test_wave1_or_latter_half_on_steady_decline(self):
        bars = _bars_decline(n=10, daily_drop=0.012)
        r = WashCycleAnalyzer().analyze("000001", bars, name="测试")
        assert r.phase in (
            WashCyclePhase.WAVE1_DECLINE,
            WashCyclePhase.LATTER_HALF_CAPITULATION,
            WashCyclePhase.WASH_EXHAUSTION,
        )
        assert r.decline_days >= 4
        assert r.cumulative_drop_pct >= 0.05
        assert "wash_then_markup" in r.related_playbook_ids
        assert r.retail_action_hint

    def test_failed_washout_on_large_drop(self):
        bars = _bars_decline(n=12, daily_drop=0.03)  # ~30%+
        r = WashCycleAnalyzer().analyze("000001", bars)
        assert r.phase == WashCyclePhase.FAILED_WASHOUT
        assert r.latter_half_cut_risk is True
        assert "止损" in r.retail_action_hint or "出货" in r.summary

    def test_second_wave_with_bounce(self):
        bars = _bars_decline(n=14, daily_drop=0.012, bounce_at=6, bounce_pct=0.025)
        r = WashCycleAnalyzer().analyze("000001", bars)
        # May land on WAVE2 or LATTER_HALF if long enough
        assert r.phase != WashCyclePhase.QUIET
        if r.wave_count >= 2:
            assert r.second_wave_active is True

    def test_earnings_window_flag(self):
        bars = _bars_decline(n=10, daily_drop=0.012)
        r = WashCycleAnalyzer().analyze("000001", bars, earnings_window=True)
        assert r.earnings_cover_flag is True
        assert any("财报" in e or "中报" in e for e in r.evidence)

    def test_to_manipulation_signal_dict(self):
        bars = _bars_decline(n=10, daily_drop=0.012)
        r = WashCycleAnalyzer().analyze("000001", bars)
        d = r.to_manipulation_signal_dict()
        assert d["playbook_id"] == "wash_then_markup"
        assert "confidence" in d


class TestWashoutDetectorIntegration:
    def test_detect_daily_attaches_wash_cycle(self):
        bars = _bars_decline(n=15, daily_drop=0.012)
        result = WashoutDetector().detect_daily("000001", bars, name="测试")
        assert result.wash_cycle is not None
        assert result.wash_cycle.phase != WashCyclePhase.QUIET
        ids = [s.playbook_id for s in result.signals]
        assert "wash_then_markup" in ids

    def test_detect_daily_can_skip_cycle(self):
        bars = _bars_decline(n=15, daily_drop=0.012)
        result = WashoutDetector().detect_daily(
            "000001", bars, include_wash_cycle=False
        )
        assert result.wash_cycle is None
        ids = [s.playbook_id for s in result.signals]
        assert "wash_then_markup" not in ids

    def test_enrich_does_not_duplicate_morphology_ids(self):
        """生命周期是 meta 信号，不应替代/复制成连阴 playbook_id。"""
        bars = _bars_decline(n=15, daily_drop=0.012)
        result = WashoutDetector().detect_daily("000001", bars)
        cycle_sigs = [s for s in result.signals if s.playbook_id == "wash_then_markup"]
        assert len(cycle_sigs) <= 1


class TestPlaybookAndSizing:
    def test_wash_then_markup_playbook_exists(self):
        ids = {p.id for p in TOP_PLAYBOOKS}
        assert "wash_then_markup" in ids
        assert "washout_consecutive_yin" in ids
        assert "shakeout" in ids

    def test_sizing_has_wash_then_markup(self):
        eng = ManipulationSizingEngine()
        assert "wash_then_markup" in eng.STOP_STRATEGIES
        strat = eng.STOP_STRATEGIES["wash_then_markup"]
        assert strat.stop_type == "wide"
        assert strat.stop_loss_pct <= -0.04
