# -*- coding: utf-8 -*-
"""P3-3 情绪维渲染接线 — 诊断输出展示 情绪(逆向) 评分行。

覆盖:
  ① step_output.print_diagnosis 展示 情绪(逆向) 0-100 评分 + 方向语义 + 原始信号
  ② output.formatter.format_analysis_result 同展示
  ③ 无 sentiment_score / sentiment_signal 字段时向后兼容 (不报错, 用默认值)
"""
from __future__ import annotations

from types import SimpleNamespace

from src.output.step_output import print_diagnosis


class TestPrintDiagnosisSentiment:
    """step_output.print_diagnosis 情绪(逆向) 行渲染。"""

    @staticmethod
    def _report(sentiment_score: float = 85.0, sentiment_signal: str = "EXTREME_PANIC"):
        return SimpleNamespace(
            sentiment_score=sentiment_score,
            sentiment_signal=sentiment_signal,
        )

    def test_shows_sentiment_reverse_score(self, capsys):
        print_diagnosis(self._report())
        out = capsys.readouterr().out
        assert "情绪(逆向)" in out
        assert "85" in out
        # 方向语义说明
        assert "高分=恐慌逆向看多" in out
        assert "低分=贪婪逆向看空" in out
        # 附原始信号
        assert "EXTREME_PANIC" in out

    def test_low_score_greed_semantics(self, capsys):
        print_diagnosis(self._report(sentiment_score=15.0, sentiment_signal="GREED"))
        out = capsys.readouterr().out
        assert "情绪(逆向)" in out
        assert "15" in out

    def test_backward_compat_missing_field(self, capsys):
        """无 sentiment_score/signal 字段 → 不报错, 用默认值 50 渲染。"""
        print_diagnosis(SimpleNamespace())
        out = capsys.readouterr().out
        assert "情绪(逆向)" in out
        assert "50" in out


class TestFormatAnalysisResultSentiment:
    """output.formatter.format_analysis_result 情绪(逆向) 行渲染。"""

    @staticmethod
    def _result(sentiment_score: float = 85.0, sentiment_signal: str = "EXTREME_PANIC"):
        from src.routing.diagnosis import DiagnosisReport
        from src.routing.orchestrator import OrchestratorResult

        report = DiagnosisReport(symbol="000001", name="平安银行")
        report.sentiment_score = sentiment_score
        report.sentiment_signal = sentiment_signal
        return OrchestratorResult(symbol="000001", name="平安银行", report=report)

    def test_shows_sentiment_reverse_score(self):
        from src.output.formatter import format_analysis_result

        out = format_analysis_result(self._result())
        assert "情绪(逆向)" in out
        assert "85" in out
        assert "高分=恐慌逆向看多" in out
        assert "EXTREME_PANIC" in out

    def test_backward_compat_missing_field(self):
        """report 无 sentiment_score → 用默认值 50, 不报错。"""
        from src.routing.diagnosis import DiagnosisReport
        from src.routing.orchestrator import OrchestratorResult

        report = DiagnosisReport(symbol="000001", name="平安银行")  # 默认 sentiment_score=50
        result = OrchestratorResult(symbol="000001", name="平安银行", report=report)

        from src.output.formatter import format_analysis_result

        out = format_analysis_result(result)
        assert "情绪(逆向)" in out
        assert "50" in out
