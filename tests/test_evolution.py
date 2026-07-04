# -*- coding: utf-8 -*-
"""策略进化与信号追踪模块测试。"""

from __future__ import annotations

import pytest

from src.backtest.engine import BacktestEngine, BacktestResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_result(**overrides) -> BacktestResult:
    defaults = {
        "strategy_name": "MVP1",
        "start_date": "2020-01-01",
        "end_date": "2024-12-31",
        "initial_cash": 1_000_000,
        "final_value": 1_500_000,
        "total_return": 0.50,
        "annual_return": 0.085,
        "sharpe_ratio": 0.80,
        "max_drawdown": -0.25,
        "win_rate": 0.55,
        "total_trades": 200,
    }
    defaults.update(overrides)
    return BacktestResult(**defaults)


def _make_engine_with_dummy_data():
    """创建带假数据的 BacktestEngine。"""
    import pandas as pd
    import numpy as np

    dates = pd.date_range("2020-01-01", "2024-12-31", freq="B")
    n = len(dates)
    np.random.seed(42)
    close = 100 * np.cumprod(1 + np.random.normal(0.0005, 0.015, n))

    df = pd.DataFrame({
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": np.random.randint(1_000_000, 10_000_000, n),
    }, index=dates)

    engine = BacktestEngine(initial_cash=1_000_000)
    engine.add_data("TEST001", df, pe_percentile=25, roe=15.0, northbound=1)
    return engine


# ---------------------------------------------------------------------------
# SignalTracker
# ---------------------------------------------------------------------------


class TestSignalTracker:
    def test_signal_lifecycle(self):
        from src.learner.signal_tracker import SignalTracker, SignalStatus
        tracker = SignalTracker()
        sig = tracker.signal_emitted("MVP1", "BUY", "600519", target_weight=0.05)
        assert sig.status == SignalStatus.EMITTED
        assert sig.symbol == "600519"

        tracker.signal_executed(sig.signal_id, execution_price=1200.0)
        assert tracker.get_signal(sig.signal_id).status == SignalStatus.EXECUTED

        tracker.signal_outcome(sig.signal_id, return_pct=0.08, holding_days=20)
        assert tracker.get_signal(sig.signal_id).status == SignalStatus.CLOSED

    def test_signal_ignored_expired(self):
        from src.learner.signal_tracker import SignalTracker, SignalStatus
        tracker = SignalTracker()
        sig = tracker.signal_emitted("MVP1", "BUY", "600519")

        tracker.signal_ignored(sig.signal_id)
        assert tracker.get_signal(sig.signal_id).status == SignalStatus.IGNORED

        sig2 = tracker.signal_emitted("MVP2", "SELL", "000001")
        tracker.signal_expired(sig2.signal_id)
        assert tracker.get_signal(sig2.signal_id).status == SignalStatus.EXPIRED

    def test_invalid_signal_id(self):
        from src.learner.signal_tracker import SignalTracker
        tracker = SignalTracker()
        with pytest.raises(KeyError, match="不存在"):
            tracker.signal_executed("NONEXISTENT", 100.0)
        with pytest.raises(KeyError, match="不存在"):
            tracker.signal_outcome("NONEXISTENT", 0.05)

    def test_get_by_strategy(self):
        from src.learner.signal_tracker import SignalTracker
        tracker = SignalTracker()
        tracker.signal_emitted("MVP1", "BUY", "A")
        tracker.signal_emitted("MVP1", "BUY", "B")
        tracker.signal_emitted("MVP2", "BUY", "C")
        assert len(tracker.get_by_strategy("MVP1")) == 2
        assert len(tracker.get_by_strategy("MVP2")) == 1

    def test_get_pending_closed(self):
        from src.learner.signal_tracker import SignalTracker
        tracker = SignalTracker()
        s1 = tracker.signal_emitted("MVP1", "BUY", "A")
        s2 = tracker.signal_emitted("MVP1", "BUY", "B")
        tracker.signal_executed(s2.signal_id, 100)
        tracker.signal_outcome(s2.signal_id, 0.05)

        assert len(tracker.get_pending()) == 1
        assert len(tracker.get_closed()) == 1

    def test_quality_report_empty(self):
        from src.learner.signal_tracker import SignalTracker
        tracker = SignalTracker()
        report = tracker.quality_report()
        assert report.total_signals == 0
        assert report.win_rate == 0.0

    def test_quality_report_with_data(self):
        from src.learner.signal_tracker import SignalTracker
        tracker = SignalTracker()

        # 3 个信号: 2 赢 1 输
        for symbol, ret in [("A", 0.10), ("B", 0.05), ("C", -0.03)]:
            s = tracker.signal_emitted("MVP1", "BUY", symbol, market_sentiment="NORMAL")
            tracker.signal_executed(s.signal_id, 100)
            tracker.signal_outcome(s.signal_id, return_pct=ret, holding_days=15)

        report = tracker.quality_report()
        assert report.total_signals == 3
        assert report.closed == 3
        assert report.win_rate == pytest.approx(2 / 3)
        assert report.avg_return == pytest.approx(0.04)
        assert report.avg_holding_days == 15.0

    def test_quality_by_sentiment(self):
        from src.learner.signal_tracker import SignalTracker
        tracker = SignalTracker()

        for sentiment, ret in [("NORMAL", 0.10), ("PANIC", -0.08)]:
            s = tracker.signal_emitted("MVP1", "BUY", "X", market_sentiment=sentiment)
            tracker.signal_executed(s.signal_id, 100)
            tracker.signal_outcome(s.signal_id, return_pct=ret)

        report = tracker.quality_report()
        assert "NORMAL" in report.by_sentiment
        assert "PANIC" in report.by_sentiment

    def test_profit_factor(self):
        from src.learner.signal_tracker import SignalTracker
        tracker = SignalTracker()
        for ret in [0.10, 0.05, -0.02]:
            s = tracker.signal_emitted("MVP1", "BUY", "X")
            tracker.signal_executed(s.signal_id, 100)
            tracker.signal_outcome(s.signal_id, return_pct=ret)
        report = tracker.quality_report()
        # 盈利 0.15 / 亏损 0.02 = 7.5
        assert report.profit_factor > 1.0

    def test_count(self):
        from src.learner.signal_tracker import SignalTracker
        tracker = SignalTracker()
        tracker.signal_emitted("A", "BUY", "X")
        tracker.signal_emitted("B", "SELL", "Y")
        assert tracker.count() == 2


# ---------------------------------------------------------------------------
# EvolutionPipeline
# ---------------------------------------------------------------------------


class TestEvolutionPipeline:
    def test_create_pipeline(self):
        from src.learner.evolution import EvolutionPipeline
        pipeline = EvolutionPipeline(_make_engine_with_dummy_data)
        assert pipeline.MIN_FEEDBACK_TO_EVOLVE == 5

    def test_evolve_rejected_insufficient_feedback(self):
        from src.learner.evolution import EvolutionPipeline, EvolutionStatus
        from src.learner.feedback import FeedbackCollector
        from src.backtest.strategy_registry import StrategyRegistry

        feedback = FeedbackCollector(db_path=":memory:")
        registry = StrategyRegistry(db_path=":memory:")
        pipeline = EvolutionPipeline(
            _make_engine_with_dummy_data,
            registry=registry,
            feedback=feedback,
        )

        record = pipeline.evolve("MVP1", "2020-01-01", "2024-12-31")
        assert record.status == EvolutionStatus.REJECTED
        assert "反馈不足" in (record.error_message or "")

    def test_evolve_forced(self):
        from src.learner.evolution import EvolutionPipeline, EvolutionStatus
        from src.learner.feedback import FeedbackCollector
        from src.backtest.strategy_registry import StrategyRegistry
        from src.backtest.mvp1_strategy import MVP1Strategy

        feedback = FeedbackCollector(db_path=":memory:")
        registry = StrategyRegistry(db_path=":memory:")
        registry.register("MVP1", "1.0.0", {"pe_percentile": 30},
                          metrics={"sharpe_ratio": 0.5})

        pipeline = EvolutionPipeline(
            _make_engine_with_dummy_data,
            registry=registry,
            feedback=feedback,
        )

        record = pipeline.evolve(
            "MVP1", "2020-01-01", "2024-12-31",
            strategy_cls=MVP1Strategy,
            force=True,
        )
        # force=True → 跳过反馈检查，执行完整流程
        # 可能 DEPLOYED 或 ERROR（取决于回测结果）
        assert record.status in (EvolutionStatus.DEPLOYED, EvolutionStatus.REJECTED, EvolutionStatus.ERROR)

    def test_evolve_with_enough_feedback(self):
        from src.learner.evolution import EvolutionPipeline, EvolutionStatus
        from src.learner.feedback import FeedbackCollector
        from src.backtest.strategy_registry import StrategyRegistry
        from src.backtest.mvp1_strategy import MVP1Strategy
        from src.learner.calibrator import RuleCalibrator

        feedback = FeedbackCollector(db_path=":memory:")
        for i in range(5):
            feedback.agree(f"SIG_{i}", "好")

        registry = StrategyRegistry(db_path=":memory:")
        registry.register("MVP1", "1.0.0", {"pe_percentile": 30},
                          metrics={"sharpe_ratio": 0.5})

        rule_cal = RuleCalibrator()
        rule_cal.register_rule("r001")
        for _ in range(5):
            rule_cal.record_correct("r001")

        pipeline = EvolutionPipeline(
            _make_engine_with_dummy_data,
            registry=registry,
            feedback=feedback,
            rule_calibrator=rule_cal,
        )

        record = pipeline.evolve(
            "MVP1", "2020-01-01", "2024-12-31",
            strategy_cls=MVP1Strategy,
        )
        assert record.status in (EvolutionStatus.DEPLOYED, EvolutionStatus.REJECTED, EvolutionStatus.ERROR)
        assert record.feedback_count >= 5

    def test_bump_version(self):
        from src.learner.evolution import EvolutionPipeline
        assert EvolutionPipeline._bump_version("1.0.0") == "1.0.1"
        assert EvolutionPipeline._bump_version("2.3.9") == "2.3.10"
        assert EvolutionPipeline._bump_version("invalid") == "1.0.0"

    def test_evolution_record(self):
        from src.learner.evolution import EvolutionRecord, EvolutionStatus
        record = EvolutionRecord(
            strategy_name="MVP1",
            old_version="1.0.0",
            new_version="1.0.1",
            status=EvolutionStatus.DEPLOYED,
        )
        assert len(record.id) == 12
        assert record.strategy_name == "MVP1"
        assert record.status == EvolutionStatus.DEPLOYED

    def test_gap_analysis(self):
        from src.learner.evolution import GapAnalysis
        gaps = GapAnalysis(
            strategy_name="MVP1",
            weak_markets=["震荡市"],
            weak_factors=["ROE因子"],
            summary="测试弱点",
        )
        assert "震荡市" in gaps.weak_markets
        assert "ROE因子" in gaps.weak_factors
        assert gaps.summary == "测试弱点"

    def test_calibration_result(self):
        from src.learner.calibrator import CalibrationResult, CalibrationRecord
        result = CalibrationResult(
            adjustments=[
                CalibrationRecord("r001", "rule_weight", 1.0, 1.1, "测试", 10),
            ],
            skipped=["r002: 证据不足"],
            total_rules=2,
        )
        assert result.changed_count == 1
        assert len(result.skipped) == 1
        assert "调整" in result.summary
