# -*- coding: utf-8 -*-
"""Phase 3-4 测试: CLI, Journal, Calibrator, Profile。"""

from __future__ import annotations

import pytest


class TestCLI:
    def test_import(self):
        from src.cli import main
        assert callable(main)

    def test_sentiment(self):
        from src.cli import cmd_sentiment
        cmd_sentiment()  # Should not crash

    def test_game_theory(self):
        from src.cli import cmd_game_theory
        cmd_game_theory()  # Should not crash

    def test_calibrate(self):
        from src.cli import cmd_calibrate
        cmd_calibrate()

    def test_profile(self):
        from src.cli import cmd_profile
        cmd_profile()

    def test_macro(self):
        from src.cli import cmd_macro
        cmd_macro()


class TestDecisions:
    def test_journal_log(self):
        from src.learner import DecisionJournal
        j = DecisionJournal()
        j.log("600519", "BUY", "BUY", "觉得便宜", "NORMAL")
        j.log("000001", "SELL", "HOLD", "再看看", "PANIC")
        assert j.count() == 2

    def test_weekly_review(self):
        from src.learner import DecisionJournal
        j = DecisionJournal()
        j.log("600519", "BUY", "BUY", "同意系统", "NORMAL")
        report = j.weekly_review()
        assert "600519" in report
        assert "100%" in report  # 1/1 agreement

    def test_empty_journal(self):
        from src.learner import DecisionJournal
        j = DecisionJournal()
        assert "无交易" in j.weekly_review()


class TestCalibrator:
    def test_insufficient_samples(self):
        from src.learner.calibrator import Calibrator
        c = Calibrator()
        for i in range(15):
            c.record(0.8, True)
        report = c.generate_report("2026-07")
        assert not report.sample_sufficient
        assert report.total_predictions == 15

    def test_sufficient_samples(self):
        from src.learner.calibrator import Calibrator
        c = Calibrator()
        for i in range(20):
            c.record(0.8, i % 2 == 0)  # ~50% accuracy
        report = c.generate_report("2026-07")
        assert report.sample_sufficient
        assert report.accuracy_by_band is not None


class TestProfile:
    def test_empty_profile(self):
        from src.learner.profile import ProfileTracker
        tracker = ProfileTracker()
        profile = tracker.evaluate()
        assert profile.stock_selection == 50.0

    def test_profile_after_trades(self):
        from src.learner.profile import ProfileTracker
        tracker = ProfileTracker()
        for i in range(10):
            tracker.record_trade(
                symbol=f"6005{i:02d}",
                is_independent=True,
                return_1m=0.05,
                benchmark_return_1m=0.02,
                stop_loss_executed=True,
                stop_loss_needed=True,
                followed_system=True,
            )
        profile = tracker.evaluate()
        assert profile.stock_selection > 50  # 3% excess → score up
        assert profile.risk_discipline == 100.0  # 10/10 executed
        assert profile.emotion_control == 100.0  # 10/10 followed

    def test_poor_discipline(self):
        from src.learner.profile import ProfileTracker
        tracker = ProfileTracker()
        tracker.record_trade(
            symbol="600519",
            is_independent=False,
            return_1m=-0.10,
            benchmark_return_1m=0.01,
            stop_loss_executed=False,  # Did not execute stop loss
            stop_loss_needed=True,      # But should have
            followed_system=False,       # Did not follow
        )
        profile = tracker.evaluate()
        assert profile.risk_discipline == 0.0  # 0/1 executed
        assert profile.emotion_control == 0.0  # 0/1 followed


class TestHuataiAdapter:
    def test_available_check(self):
        from src.data.huatai import HuataiProvider
        h = HuataiProvider()
        # Should work without crashing
        assert isinstance(h.available, bool)
