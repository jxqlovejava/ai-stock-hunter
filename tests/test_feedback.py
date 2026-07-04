# -*- coding: utf-8 -*-
"""用户反馈与校准模块测试。"""

from __future__ import annotations

import os
import tempfile

import pytest


# ---------------------------------------------------------------------------
# FeedbackCollector
# ---------------------------------------------------------------------------


class TestFeedbackCollector:
    def test_agree(self):
        from src.learner.feedback import FeedbackCollector, FeedbackType
        collector = FeedbackCollector(db_path=":memory:")
        fb = collector.agree("SIG_001", "看好基本面")
        assert fb.type == FeedbackType.AGREE
        assert fb.signal_id == "SIG_001"
        assert collector.count() == 1

    def test_disagree(self):
        from src.learner.feedback import FeedbackCollector, FeedbackType
        collector = FeedbackCollector(db_path=":memory:")
        fb = collector.disagree("SIG_002", "估值太高", user_action="HOLD")
        assert fb.type == FeedbackType.DISAGREE
        assert fb.user_action == "HOLD"

    def test_adjust(self):
        from src.learner.feedback import FeedbackCollector, FeedbackType
        collector = FeedbackCollector(db_path=":memory:")
        fb = collector.adjust("SIG_003", "stop_loss_pct", -0.15, -0.20, "波动大")
        assert fb.type == FeedbackType.ADJUST
        assert fb.old_value == -0.15
        assert fb.new_value == -0.20

    def test_annotate_outcome(self):
        from src.learner.feedback import FeedbackCollector, FeedbackType
        collector = FeedbackCollector(db_path=":memory:")
        fb = collector.annotate_outcome("SIG_001", 0.08, "获利 8%", holding_days=20)
        assert fb.type == FeedbackType.ANNOTATE
        assert fb.actual_return == 0.08
        assert fb.holding_days == 20

    def test_summary_agreement_rate(self):
        from src.learner.feedback import FeedbackCollector
        collector = FeedbackCollector(db_path=":memory:")
        collector.agree("SIG_001")
        collector.agree("SIG_002")
        collector.disagree("SIG_003", "太贵")
        collector.disagree("SIG_004", "风险高")
        summary = collector.summary()
        assert summary.total == 4
        assert summary.agreement_rate == 0.5
        assert summary.agree_count == 2
        assert summary.disagree_count == 2

    def test_summary_by_strategy(self):
        from src.learner.feedback import FeedbackCollector
        collector = FeedbackCollector(db_path=":memory:")
        collector.agree("S_1", strategy_name="MVP1")
        collector.disagree("S_2", "贵", strategy_name="MVP1")
        collector.agree("S_3", strategy_name="MVP2")
        summary = collector.summary(strategy_name="MVP1")
        assert summary.total == 2

    def test_get_by_signal(self):
        from src.learner.feedback import FeedbackCollector
        collector = FeedbackCollector(db_path=":memory:")
        collector.agree("SIG_A")
        collector.annotate_outcome("SIG_A", 0.05)
        items = collector.get_by_signal("SIG_A")
        assert len(items) == 2

    def test_get_disagreements(self):
        from src.learner.feedback import FeedbackCollector
        collector = FeedbackCollector(db_path=":memory:")
        collector.agree("S_1")
        collector.disagree("S_2", "贵")
        collector.disagree("S_3", "风险")
        assert len(collector.get_disagreements()) == 2

    def test_get_adjustments(self):
        from src.learner.feedback import FeedbackCollector
        collector = FeedbackCollector(db_path=":memory:")
        collector.adjust("S_1", "stop_loss", -0.15, -0.20)
        collector.adjust("S_2", "stop_loss", -0.20, -0.25)
        collector.adjust("S_3", "pe_threshold", 30, 25)
        assert len(collector.get_adjustments("stop_loss")) == 2
        assert len(collector.get_adjustments("pe_threshold")) == 1

    def test_recent(self):
        from src.learner.feedback import FeedbackCollector
        collector = FeedbackCollector(db_path=":memory:")
        collector.agree("S_1")
        recent = collector.recent(days=30)
        assert len(recent) == 1

    def test_persistence(self):
        from src.learner.feedback import FeedbackCollector, FeedbackType
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "feedback.json")
            c1 = FeedbackCollector(db_path=path)
            c1.agree("SIG_001", "好")
            c1.disagree("SIG_002", "贵")

            c2 = FeedbackCollector(db_path=path)
            assert c2.count() == 2
            assert c2.get_by_signal("SIG_001")[0].type == FeedbackType.AGREE


# ---------------------------------------------------------------------------
# RuleCalibrator
# ---------------------------------------------------------------------------


class TestRuleCalibrator:
    def test_register_and_calibrate(self):
        from src.learner.calibrator import RuleCalibrator
        cal = RuleCalibrator()
        cal.register_rule("r001", initial_weight=1.0)

        # 不足 5 条证据 → 跳过
        cal.record_correct("r001")
        result = cal.calibrate()
        assert result.changed_count == 0
        assert len(result.skipped) == 1

    def test_calibrate_with_enough_evidence(self):
        from src.learner.calibrator import RuleCalibrator
        cal = RuleCalibrator()
        cal.register_rule("r001", initial_weight=1.0)

        # 足够证据：3 次正确 + 2 次漏报
        for _ in range(3):
            cal.record_correct("r001")
        for _ in range(2):
            cal.record_false_negative("r001")

        result = cal.calibrate()
        assert result.changed_count >= 1
        # 漏报多 → 权重点上调
        adj = result.adjustments[0]
        assert adj.new_value > adj.old_value

    def test_fp_reduces_weight(self):
        from src.learner.calibrator import RuleCalibrator
        cal = RuleCalibrator()
        cal.register_rule("r001", initial_weight=1.0)

        # 误报多 → 权重下调
        for _ in range(5):
            cal.record_false_positive("r001")
        for _ in range(1):
            cal.record_correct("r001")

        result = cal.calibrate()
        adj = result.adjustments[0]
        assert adj.new_value < adj.old_value

    def test_rollback(self):
        from src.learner.calibrator import RuleCalibrator
        cal = RuleCalibrator()
        cal.register_rule("r001", initial_weight=1.0)

        for _ in range(10):
            cal.record_correct("r001")
        original = cal.get_weights()["r001"]
        cal.calibrate()
        cal.rollback_last()
        assert cal.get_weights()["r001"] == original

    def test_max_adjustment_limit(self):
        from src.learner.calibrator import RuleCalibrator
        cal = RuleCalibrator()
        cal.register_rule("r001", initial_weight=1.0)

        # 全是漏报 → 权重大幅上调，但被限制在 10%
        for _ in range(10):
            cal.record_false_negative("r001")

        result = cal.calibrate()
        adj = result.adjustments[0]
        assert adj.new_value <= adj.old_value * 1.10 + 0.001

    def test_batch_register(self):
        from src.learner.calibrator import RuleCalibrator
        cal = RuleCalibrator()
        cal.register_rules(["r001", "r002", "r003"])
        assert len(cal.get_weights()) == 3


# ---------------------------------------------------------------------------
# FactorCalibrator
# ---------------------------------------------------------------------------


class TestFactorCalibrator:
    def test_calibrate_with_feedback(self):
        from src.learner.calibrator import FactorCalibrator
        cal = FactorCalibrator()
        cal.register_factor("pe", initial_weight=0.40, sharpe=0.8)
        cal.register_factor("roe", initial_weight=0.40, sharpe=0.5)
        cal.register_factor("northbound", initial_weight=0.20, sharpe=0.3)

        # 用户对 pe 因子高度赞同
        for _ in range(5):
            cal.record_feedback("pe", agreed=True)

        result = cal.calibrate()
        # pe 权重应上升（高夏普 + 高赞同）
        weights = cal.get_weights()
        assert sum(weights.values()) == pytest.approx(1.0, abs=0.01)

    def test_insufficient_evidence_skipped(self):
        from src.learner.calibrator import FactorCalibrator
        cal = FactorCalibrator()
        cal.register_factor("pe", initial_weight=0.50)
        cal.record_feedback("pe", agreed=True)  # only 1 feedback

        result = cal.calibrate()
        assert len(result.skipped) >= 1
        assert "pe" in result.skipped[0]


# ---------------------------------------------------------------------------
# RiskParamCalibrator
# ---------------------------------------------------------------------------


class TestRiskParamCalibrator:
    def test_calibrate_stop_loss(self):
        from src.learner.calibrator import RiskParamCalibrator
        cal = RiskParamCalibrator()
        cal.register_param("stop_loss_pct", -0.15)

        # 实际亏损持续超出止损线
        for _ in range(3):
            cal.record_event(
                "stop_loss_pct", set_value=-0.15,
                actual_value=-0.22, reason="波动超出预期"
            )

        result = cal.calibrate()
        assert result.changed_count >= 1
        new_val = cal.get_values()["stop_loss_pct"]
        # 应扩大止损（更负）
        assert new_val < -0.15

    def test_insufficient_events(self):
        from src.learner.calibrator import RiskParamCalibrator
        cal = RiskParamCalibrator()
        cal.register_param("stop_loss_pct", -0.15)
        cal.record_event("stop_loss_pct", -0.15, -0.18)  # only 1

        result = cal.calibrate()
        assert result.changed_count == 0


# ---------------------------------------------------------------------------
# Calibrator (confidence, old API)
# ---------------------------------------------------------------------------


class TestConfidenceCalibrator:
    def test_record_and_report(self):
        from src.learner.calibrator import Calibrator
        cal = Calibrator()
        assert cal.MIN_SAMPLES == 20

        # 不足 20 → sample_sufficient=False
        for _ in range(10):
            cal.record(0.85, actual_outcome=True)
        report = cal.generate_report()
        assert not report.sample_sufficient

    def test_report_with_enough_samples(self):
        from src.learner.calibrator import Calibrator
        cal = Calibrator()
        for _ in range(20):
            cal.record(0.85, actual_outcome=True)
        report = cal.generate_report()
        assert report.sample_sufficient
        assert report.accuracy_by_band is not None


# ---------------------------------------------------------------------------
# ReportGenerator
# ---------------------------------------------------------------------------


class TestReportGenerator:
    def test_generate_basic(self):
        from src.learner.report import ReportGenerator
        gen = ReportGenerator()
        report = gen.generate(period="weekly")
        assert report.title == "周度学习报告"
        assert "建议" in report.render()

    def test_generate_with_profile(self):
        from src.learner.profile import UserProfile
        from src.learner.report import ReportGenerator
        profile = UserProfile(
            stock_selection=70,
            timing=60,
            risk_discipline=80,
            emotion_control=50,
        )
        gen = ReportGenerator()
        report = gen.generate(profile=profile)
        assert "70" in report.render()
        assert report.profile_snapshot["选股能力"] == 70

    def test_generate_with_strategy_versions(self):
        from src.learner.report import ReportGenerator, LearningReport
        gen = ReportGenerator()
        report = gen.generate(strategy_versions=[], period="monthly")
        assert "暂无策略优化记录" in report.render()

    def test_generate_with_risk_alerts(self):
        from src.learner.report import ReportGenerator
        # 模拟信号质量差的场景
        class FakeSignalQuality:
            win_rate = 0.35
            avg_return = -0.08
            max_drawdown = -0.25

        gen = ReportGenerator()
        report = gen.generate(signal_quality=FakeSignalQuality())
        rendered = report.render()
        assert "胜率偏低" in rendered or "风险提示" in rendered
