# -*- coding: utf-8 -*-
"""信号追踪器相对基准 alpha 复盘 + 跨标的教训注入测试。"""

from __future__ import annotations

from src.learner.signal_tracker import SignalTracker


def _seed(tracker: SignalTracker) -> None:
    """构造 3 条已平仓信号: 同标的 2 条 + 跨标 1 条。"""
    # 600519 第一条: 收益 8%, 基准 2% → alpha +6%
    s1 = tracker.signal_emitted("MVP1", "BUY", "600519", market_sentiment="BULLISH", hs300_change_pct=0.02)
    tracker.signal_outcome(s1.signal_id, return_pct=0.08, holding_days=10, exit_reason="target hit", benchmark_return_pct=0.02)
    # 600519 第二条: 收益 -3%, 无显式基准 → 回退 hs300_change_pct 0.01 → alpha -4%
    s2 = tracker.signal_emitted("MVP1", "SELL", "600519", hs300_change_pct=0.01)
    tracker.signal_outcome(s2.signal_id, return_pct=-0.03, holding_days=5, exit_reason="stop")
    # 000858 跨标: 收益 5%, 基准 4% → alpha +1%
    s3 = tracker.signal_emitted("MVP2", "BUY", "000858", hs300_change_pct=0.04)
    tracker.signal_outcome(s3.signal_id, return_pct=0.05, holding_days=8, exit_reason="target hit", benchmark_return_pct=0.04)


class TestAlphaOutcome:
    def test_alpha_computed_from_benchmark(self):
        t = SignalTracker()
        _seed(t)
        s1 = t.get_by_strategy("MVP1")[0]
        assert s1.alpha_return_pct == 0.06  # 0.08 - 0.02

    def test_alpha_falls_back_to_hs300(self):
        t = SignalTracker()
        _seed(t)
        s2 = t.get_by_strategy("MVP1")[1]
        assert s2.alpha_return_pct == -0.04  # -0.03 - 0.01

    def test_benchmark_return_stored(self):
        t = SignalTracker()
        _seed(t)
        s3 = t.get_by_strategy("MVP2")[0]
        assert s3.benchmark_return_pct == 0.04
        assert s3.alpha_return_pct == 0.01


class TestLessons:
    def test_same_then_cross_ordering(self):
        t = SignalTracker()
        _seed(t)
        text = t.get_lessons("600519")
        # 同标在前
        assert text.index("同标的历史信号 (600519)") < text.index("跨标的教训")
        assert "000858" in text
        assert "600519" in text

    def test_lessons_include_alpha(self):
        t = SignalTracker()
        _seed(t)
        text = t.get_lessons("600519")
        assert "+6.00% (vs hs300)" in text or "6.00%" in text

    def test_no_closed_returns_empty(self):
        t = SignalTracker()
        t.signal_emitted("MVP1", "BUY", "600519")
        assert t.get_lessons("600519") == ""

    def test_cross_only_when_symbol_none(self):
        t = SignalTracker()
        _seed(t)
        text = t.get_lessons()
        assert "跨标的教训" in text


class TestQualityReportAlpha:
    def test_avg_alpha_and_win_rate(self):
        t = SignalTracker()
        _seed(t)
        r = t.quality_report()
        # alphas = +6%, -4%, +1% → avg +1%
        assert abs(r.avg_alpha_return - 0.01) < 1e-9
        assert r.alpha_win_rate == 2 / 3
