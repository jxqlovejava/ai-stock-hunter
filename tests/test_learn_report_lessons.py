# -*- coding: utf-8 -*-
"""M4: learn report 跨标的教训注入 + alpha 风险告警测试。"""

from __future__ import annotations

from types import SimpleNamespace

from src.learner.report import LearningReport, ReportGenerator


class TestLessonsRender:
    def test_lessons_section_rendered_when_nonempty(self):
        report = LearningReport(title="周度学习报告", period="weekly")
        report.lessons = "### 同标的历史信号 (600519)\n- 600519 BUY 收益 +5.00% alpha +3.00%"
        out = report.render()
        assert "## 📚 复盘教训" in out
        assert "600519 BUY" in out

    def test_lessons_section_omitted_when_empty(self):
        report = LearningReport(title="周度学习报告", period="weekly")
        out = report.render()
        assert "复盘教训" not in out


class TestGenerateLessonsWiring:
    def test_generate_accepts_lessons(self):
        gen = ReportGenerator()
        report = gen.generate(lessons="### 跨标的教训\n- 000858 BUY alpha +1%")
        assert report.lessons.startswith("### 跨标的教训")

    def test_generate_negative_alpha_adds_alert(self):
        sq = SimpleNamespace(
            win_rate=0.6,
            avg_return=0.02,
            max_drawdown=-0.05,
            avg_alpha_return=-0.05,
            alpha_win_rate=0.3,
        )
        gen = ReportGenerator()
        report = gen.generate(signal_quality=sq)
        assert any("alpha" in a.lower() for a in report.risk_alerts)

    def test_generate_positive_alpha_no_alert(self):
        sq = SimpleNamespace(
            win_rate=0.6,
            avg_return=0.02,
            max_drawdown=-0.05,
            avg_alpha_return=0.03,
            alpha_win_rate=0.6,
        )
        gen = ReportGenerator()
        report = gen.generate(signal_quality=sq)
        assert not any("alpha" in a.lower() for a in report.risk_alerts)
