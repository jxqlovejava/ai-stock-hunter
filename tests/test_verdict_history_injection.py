# -*- coding: utf-8 -*-
"""机制5: conclusion_ledger 历史结论注入综合裁决测试。"""

from __future__ import annotations

from unittest import mock

from src.routing.diagnosis import DiagnosisReport
from src.routing.verdict import VerdictEngine


def _report(symbol: str = "600519", score: float = 60.0) -> DiagnosisReport:
    return DiagnosisReport(
        symbol=symbol,
        name="测试公司",
        value_score=score,
        quality_score=score,
        momentum_score=score,
        valuation_score=score,
        macro_score=score,
        cycle_score=score,
        sentiment_signal="NEUTRAL",
    )


def _timeline(verdicts: list[dict]) -> list[dict]:
    """构造结论时间线条目。"""
    entries = []
    for i, v in enumerate(verdicts):
        entries.append({
            "date": f"2026-08-0{i + 1}",
            "verdict": v["verdict"],
            "score": v.get("score", 55.0),
            "confidence": v.get("confidence", 0.6),
            "one_line": v.get("one_line", "测试结论"),
        })
    return entries


class TestHistoryAdjustment:
    def test_no_ledger_no_adjustment(self):
        with mock.patch(
            "src.analysis.conclusion_ledger.load_stock_timeline", return_value=[]
        ):
            ctx, adj, div = VerdictEngine()._history_adjustment("600519", "BUY")
        assert ctx == ""
        assert adj == 0.0
        assert div is False

    def test_consistent_direction_boosts(self):
        tl = _timeline([{"verdict": "BUY"}, {"verdict": "ADD"}, {"verdict": "BUY"}])
        with mock.patch(
            "src.analysis.conclusion_ledger.load_stock_timeline", return_value=tl
        ):
            ctx, adj, div = VerdictEngine()._history_adjustment("600519", "BUY")
        assert ctx != ""
        assert adj == 0.015
        assert div is False

    def test_divergent_direction_penalizes(self):
        tl = _timeline([{"verdict": "BUY"}, {"verdict": "BUY"}, {"verdict": "ADD"}])
        with mock.patch(
            "src.analysis.conclusion_ledger.load_stock_timeline", return_value=tl
        ):
            ctx, adj, div = VerdictEngine()._history_adjustment("600519", "SELL")
        assert adj == -0.03
        assert div is True

    def test_insufficient_entries_no_adjustment(self):
        tl = _timeline([{"verdict": "BUY"}])
        with mock.patch(
            "src.analysis.conclusion_ledger.load_stock_timeline", return_value=tl
        ):
            ctx, adj, div = VerdictEngine()._history_adjustment("600519", "BUY")
        assert adj == 0.0
        assert div is False

    def test_ledger_error_is_defensive(self):
        with mock.patch(
            "src.analysis.conclusion_ledger.load_stock_timeline",
            side_effect=RuntimeError("boom"),
        ):
            ctx, adj, div = VerdictEngine()._history_adjustment("600519", "BUY")
        assert (ctx, adj, div) == ("", 0.0, False)


class TestJudgeInjection:
    def test_judge_injects_history_context(self):
        tl = _timeline([{"verdict": "ADD"}, {"verdict": "ADD"}, {"verdict": "BUY"}])
        with mock.patch(
            "src.analysis.conclusion_ledger.load_stock_timeline", return_value=tl
        ):
            verdict = VerdictEngine().judge(_report())
        assert "历史结论背景" in verdict.history_context
        assert verdict.history_adjustment > 0  # 同向 → 加信

    def test_judge_divergence_adds_risk(self):
        tl = _timeline([{"verdict": "BUY"}, {"verdict": "BUY"}, {"verdict": "BUY"}])
        with mock.patch(
            "src.analysis.conclusion_ledger.load_stock_timeline", return_value=tl
        ):
            verdict = VerdictEngine().judge(_report(score=20.0))  # 低分 → SELL
        assert verdict.history_adjustment < 0
        assert any(
            r.get("source") == "conclusion_history_divergence" for r in verdict.risks
        )

    def test_judge_no_history_ok(self):
        with mock.patch(
            "src.analysis.conclusion_ledger.load_stock_timeline", return_value=[]
        ):
            verdict = VerdictEngine().judge(_report())
        assert verdict.history_context == ""
        assert verdict.history_adjustment == 0.0
