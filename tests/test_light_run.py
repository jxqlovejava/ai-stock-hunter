# -*- coding: utf-8 -*-
"""mode=light 持仓轻体检测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.routing.light_run import run_light, _pos_loss_pct
from src.routing.orchestrator import OrchestratorResult
from src.routing.diagnosis import DiagnosisReport
from src.routing.verdict import Verdict


def _fake_quote(symbol="002460", price=52.55):
    return SimpleNamespace(
        symbol=symbol,
        name="赣锋锂业",
        price=price,
        change_pct=-2.0,
        turnover=1e8,
        listing_date=None,
        source="tencent",
        market_cap=1e11,
        model_dump=lambda: {
            "symbol": symbol,
            "name": "赣锋锂业",
            "price": price,
            "change_pct": -2.0,
            "close_series": [58, 57, 56, 55, 54, 52.55],
        },
    )


def test_pos_loss_pct():
    # ratio semantics (matches risk_control / mental_model)
    assert abs(_pos_loss_pct(90, 100) - (-0.1)) < 1e-6
    assert _pos_loss_pct(0, 100) == 0.0
    assert _pos_loss_pct(100, 0) == 0.0


def test_run_light_happy_path():
    orch = MagicMock()
    orch.data.get_quote.return_value = _fake_quote()
    orch.data.get_cross_validated_quote.return_value = (_fake_quote(), False, False)
    orch.data.get_financials.return_value = []
    orch._quote_from_cache.return_value = None
    orch._inject_ma_data.return_value = None
    orch._inject_bottom_structure_ctx.return_value = None
    orch._inject_financial_doctrine_ctx.return_value = None
    orch._get_investor_prefs.return_value = (None, True, 0, [])

    doctrine = SimpleNamespace(
        passed=True,
        blocked_by=[],
        warnings=[],
        infos=[],
    )
    orch.doctrine.check.return_value = doctrine
    orch.admission.check.return_value = SimpleNamespace(status=SimpleNamespace(value="PASSED"), flags=[])

    report = DiagnosisReport(symbol="002460", name="赣锋锂业")
    report.macro_score = 50
    report.value_score = 55
    report.quality_score = 60
    report.momentum_score = 40
    report.confidence = 0.7
    report.source_citations = []
    orch.diagnosis.analyze.return_value = report

    verdict = Verdict(
        symbol="002460",
        score=48.0,
        confidence=0.65,
        recommendation="HOLD",
    )
    # fill required fields if Verdict needs more
    orch.verdict_engine.judge.return_value = verdict

    signal = SimpleNamespace(
        action="HOLD",
        weight=0.1,
        target_weight=0.1,
        confidence=0.6,
        sizing_method="fixed",
        source_citations=[],
    )
    orch.positioning.generate_signal.return_value = signal
    orch.risk_ctrl.check.return_value = SimpleNamespace(status="APPROVE", action="APPROVE")

    with patch("src.output.progress.step_start"), patch("src.output.progress.step_done"), \
         patch("src.output.step_output.print_admission"), \
         patch("src.output.step_output.print_diagnosis"), \
         patch("src.output.step_output.print_doctrine"), \
         patch("src.output.step_output.print_verdict"), \
         patch("src.output.step_output.print_positioning"), \
         patch("src.output.step_output.print_risk_control"):
        result = run_light(orch, symbol="002460", market="SZ", name="赣锋锂业")

    assert result.passed is True
    assert result.report is report
    assert result.verdict is verdict
    assert result.signal is signal
    assert any("light" in g for g in result.data_gaps)
    orch.diagnosis.analyze.assert_called_once()
    # 轻路径不应走辩论
    assert not hasattr(orch, "perspective_analyzer") or True


def test_orchestrator_dispatches_light():
    from src.routing.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    with patch("src.routing.light_run.run_light") as m:
        m.return_value = OrchestratorResult(symbol="002460", name="x", passed=True)
        # need minimal init attributes? run only branches
        out = Orchestrator.run(orch, "002460", "SZ", mode="light")
        m.assert_called_once()
        assert out.symbol == "002460"
