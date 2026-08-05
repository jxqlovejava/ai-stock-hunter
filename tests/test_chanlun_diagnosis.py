# -*- coding: utf-8 -*-
"""缠论在 diagnosis 管道中的消费回归测试。

覆盖:
- _detect_chanlun: sell_signal/buy_signal 只看最近一个买卖点（历史误触 bug）
- step_output.print_chanlun / print_diagnosis: diagnose CLI 缠论摘要渲染
- markdown_report._build_report: Markdown 报告缠论章节
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd


class _FakeChanlunResult:
    """模拟 ChanlunAnalyzer.analyze 返回值（ChanlunResult 的轻量替身）。"""

    def __init__(self, points_kind_first: str, points_kind_last: str):
        self.bis = [object()]
        self.zhongshus = [object()]
        self.points = [
            SimpleNamespace(kind=points_kind_first, dt="2024-05-21", price=15.92, confidence=0.7),
            SimpleNamespace(kind=points_kind_last, dt="2026-07-20", price=14.91, confidence=0.7),
        ]
        self.current_state = {
            "position": "中枢下方",
            "last_point": {"kind": points_kind_last, "dt": "2026-07-20", "price": 14.91},
        }

    def to_summary_dict(self) -> dict:
        return {
            "backend": "self", "freq": "D",
            "bi_count": 1, "zhongshu_count": 1,
            "last_zs": {"zg": 26.64, "zd": 22.77, "zz": 24.70, "state": "上移"},
            "points": [
                {"kind": p.kind, "dt": str(p.dt), "price": p.price,
                 "confidence": p.confidence, "rationale": ""}
                for p in self.points
            ],
            "current_state": self.current_state,
            "signals": {"entry": [], "exit": []},
            "confidence": 0.75,
        }


def _patch_analyzer(monkeypatch, result) -> None:
    class _FakeAnalyzer:
        def __init__(self, freq="D"):
            pass

        def analyze(self, bars_df, symbol, name):
            return result

    monkeypatch.setattr(
        "src.indicators.chanlun.analyzer.ChanlunAnalyzer", _FakeAnalyzer
    )


class TestChanlunSellSignal:
    """_detect_chanlun 信号只看最近买卖点，不被历史买卖点误触。"""

    @staticmethod
    def _detect(monkeypatch, result):
        from src.routing.diagnosis import DiagnosisEngine

        _patch_analyzer(monkeypatch, result)
        bars_df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        return DiagnosisEngine._detect_chanlun("002130", "沃尔核材", bars_df)

    def test_historical_sell_latest_buy(self, monkeypatch):
        """历史卖点 + 最近买点 → sell_signal=False, buy_signal=True。"""
        res = _FakeChanlunResult(points_kind_first="一卖", points_kind_last="一买")
        out = self._detect(monkeypatch, res)
        assert out is not None
        assert out["summary"]["sell_signal"] is False
        assert out["summary"]["buy_signal"] is True

    def test_latest_sell(self, monkeypatch):
        """最近是卖点 → sell_signal=True, buy_signal=False。"""
        res = _FakeChanlunResult(points_kind_first="一买", points_kind_last="一卖")
        out = self._detect(monkeypatch, res)
        assert out is not None
        assert out["summary"]["sell_signal"] is True
        assert out["summary"]["buy_signal"] is False

    def test_no_result_when_no_bars(self):
        """bars_df 为空 → 返回 None（降级不渲染）。"""
        from src.routing.diagnosis import DiagnosisEngine

        assert DiagnosisEngine._detect_chanlun("002130", "沃尔核材", None) is None
        assert DiagnosisEngine._detect_chanlun("002130", "沃尔核材", pd.DataFrame()) is None


class TestChanlunRendering:
    """diagnose CLI / Markdown 报告能展示缠论摘要。"""

    @staticmethod
    def _report():
        ch = _FakeChanlunResult("一卖", "一买").to_summary_dict()
        return SimpleNamespace(chanlun=ch, chanlun_score=57.5)

    def test_print_chanlun_renders(self, capsys):
        from src.output.step_output import print_chanlun

        print_chanlun(self._report())
        out = capsys.readouterr().out
        assert "缠论结构" in out
        assert "最近信号" in out
        assert "中枢" in out
        assert "一买" in out

    def test_print_chanlun_skips_when_no_data(self, capsys):
        from src.output.step_output import print_chanlun

        print_chanlun(SimpleNamespace(chanlun=None))
        assert capsys.readouterr().out == ""

    def test_print_diagnosis_embeds_chanlun(self, capsys):
        from src.output.step_output import print_diagnosis

        print_diagnosis(self._report())
        out = capsys.readouterr().out
        assert "缠论结构" in out

    def test_markdown_report_includes_chanlun(self):
        from src.output.markdown_report import _build_report

        result = SimpleNamespace(
            name="沃尔核材", symbol="002130", report=self._report(),
        )
        md = "\n".join(_build_report(result))
        assert "## 🥋 缠论结构" in md
        assert "最近信号" in md
        assert "一买" in md


class TestChanlunInDiagnosisReport:
    """诊断 Report 的 chanlun 字段结构（渲染消费的契约）。"""

    def test_report_has_chanlun_attrs(self):
        from src.routing.diagnosis import DiagnosisReport

        r = DiagnosisReport(symbol="002130", name="沃尔核材")
        assert r.chanlun is None
        assert r.chanlun_score == 50.0
