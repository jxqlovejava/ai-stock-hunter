# -*- coding: utf-8 -*-
"""P2-4 置信度校准闭环 + P2-5 运气/幸存者偏差校准 测试。"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# P2-4: 校准分桶反哺 confidence
# ---------------------------------------------------------------------------


class TestCalibratorApply:
    """Calibrator.apply 分桶校正反哺 confidence。"""

    def _overconfident_calibrator(self, n: int = 20):
        """构造过度自信校准数据：confidence 0.9 但仅 60% 正确。"""
        from src.learner.calibrator import Calibrator

        cal = Calibrator()
        for i in range(n):
            cal.record(0.9, actual_outcome=(i % 5 < 3))  # 12/20 = 60%
        return cal

    def test_adjusts_down_when_overconfident(self):
        """样本充足且桶内准确率低于预测 → confidence 下调。"""
        cal = self._overconfident_calibrator()
        assert cal.adjustments_available
        adjusted = cal.apply(0.9)
        assert adjusted < 0.9
        assert 0.0 <= adjusted <= 1.0

    def test_insufficient_samples_returns_input(self):
        """样本 < MIN_SAMPLES → 原样返回。"""
        from src.learner.calibrator import Calibrator

        cal = Calibrator()
        for _ in range(10):
            cal.record(0.9, True)
        assert cal.apply(0.9) == 0.9

    def test_empty_returns_input(self):
        """无数据 → 原样返回。"""
        from src.learner.calibrator import Calibrator

        assert Calibrator().apply(0.8) == 0.8

    def test_well_calibrated_returns_input(self):
        """桶内准确率 ≥ 预测中值 → 不上调（保守）。"""
        from src.learner.calibrator import Calibrator

        cal = Calibrator()
        for _ in range(20):
            cal.record(0.9, True)  # 100% 正确 → 不需要下调
        assert cal.apply(0.9) == 0.9

    def test_band_lookup(self):
        """分桶准确率查询。"""
        cal = self._overconfident_calibrator()
        acc = cal.band_lookup()
        assert "0.9-1.0" in acc
        assert 0.5 < acc["0.9-1.0"] < 0.7


class TestApplyCalibrationSignal:
    """signal.apply_calibration 入口 + target_from_signal 集成。"""

    def test_no_calibrator_returns_input(self):
        from src.routing.signal import apply_calibration

        assert apply_calibration(0.8) == 0.8
        assert apply_calibration(0.8, calibrator=None) == 0.8

    def test_calibrator_object_without_apply_returns_input(self):
        from src.routing.signal import apply_calibration

        class Fake:
            pass

        assert apply_calibration(0.8, calibrator=Fake()) == 0.8

    def test_target_from_signal_no_calibrator_unchanged(self):
        from src.routing.signal import Direction, Signal, target_from_signal

        sig = Signal(symbol="600519", direction=Direction.UP, confidence=0.9, source_model="t")
        target = target_from_signal(sig, portfolio_value=1_000_000, current_price=100.0)
        assert target.target_weight == pytest.approx(0.45)  # 0.9 * 0.5
        # 位置参数调用仍兼容（向后兼容）
        target2 = target_from_signal(sig, 1_000_000, 100.0, "reason", 1.0)
        assert target2.target_weight == pytest.approx(0.45)

    def test_target_from_signal_with_calibrator(self):
        from src.learner.calibrator import Calibrator
        from src.routing.signal import Direction, Signal, target_from_signal

        cal = Calibrator()
        for i in range(20):
            cal.record(0.9, actual_outcome=(i % 5 < 3))  # 过度自信

        sig = Signal(symbol="600519", direction=Direction.UP, confidence=0.9, source_model="t")
        calibrated = target_from_signal(sig, 1_000_000, 100.0, calibrator=cal)
        plain = target_from_signal(sig, 1_000_000, 100.0)
        assert calibrated.target_weight < plain.target_weight
        assert "calibrated" in calibrated.reason


# ---------------------------------------------------------------------------
# P2-5: 聚合运气标记
# ---------------------------------------------------------------------------


class TestLuckAggregation:
    def test_flagged_when_profit_concentrated(self):
        """高收益集中少数几笔 + 剔除后转负 → 标记运气。"""
        from src.alpha.attribution import AlphaAttribution, LuckBiasDetector

        returns = [10.0, 8.0, 0.5, 0.3, 0.2] + [-0.33] * 15  # 20 笔
        assessment = LuckBiasDetector().assess(returns, strategy="MVP1")
        assert assessment.flagged
        assert assessment.top_profit_share >= 0.7
        assert not assessment.minus_top_still_positive
        assert "运气" in assessment.reason
        assert "剔除" in assessment.evidence

    def test_not_flagged_when_diversified(self):
        """收益分布分散 → 不标记。"""
        from src.alpha.attribution import LuckBiasDetector

        returns = [0.5] * 20
        assessment = LuckBiasDetector().assess(returns, strategy="MVP2")
        assert not assessment.flagged
        assert assessment.minus_top_still_positive

    def test_insufficient_samples_not_flagged(self):
        from src.alpha.attribution import LuckBiasDetector

        assessment = LuckBiasDetector().assess([1.0, 2.0, 3.0], strategy="X")
        assert not assessment.flagged
        assert "样本不足" in assessment.reason

    def test_attribution_static_method(self):
        """AlphaAttribution.aggregate_luck_assessment 输出聚合运气标记。"""
        from src.alpha.attribution import AlphaAttribution, LuckAssessment

        returns = [10.0, 8.0, 0.5, 0.3, 0.2] + [-0.33] * 15
        result = AlphaAttribution.aggregate_luck_assessment(returns, strategy="MVP1")
        assert isinstance(result, LuckAssessment)
        assert result.flagged


# ---------------------------------------------------------------------------
# P2-5: 幸存者偏差校正
# ---------------------------------------------------------------------------


class TestSurvivorshipAdjustment:
    def test_corrects_when_missing_strategies(self):
        from src.learner.calibrator import survivorship_adjustment

        # 幸存 10 个策略均值 0.15，但实际共 20 个（10 个被淘汰，假设均值 0）
        assert survivorship_adjustment(0.15, 10, 20) == pytest.approx(0.075)

    def test_no_change_when_all_observed(self):
        from src.learner.calibrator import survivorship_adjustment

        assert survivorship_adjustment(0.15, 20, 20) == pytest.approx(0.15)
        assert survivorship_adjustment(0.15, 0, 0) == pytest.approx(0.15)

    def test_hidden_default_return(self):
        from src.learner.calibrator import survivorship_adjustment

        # 缺失策略假设为负收益 -0.1
        assert survivorship_adjustment(0.15, 10, 20, hidden_default_return=-0.1) == pytest.approx(0.025)


# ---------------------------------------------------------------------------
# P2-5: 样本外（OOS）门禁
# ---------------------------------------------------------------------------


class TestBacktestValidatorOOS:
    def test_without_oos_unchanged(self):
        from src.evolution.backtest_validator import BacktestValidator

        r = BacktestValidator().validate(sharpe=1.2, total_return=0.5, max_dd=0.1, trades=50)
        assert r.passed
        assert r.oos_passed

    def test_oos_failure_blocks_merge(self):
        from src.backtest.walkforward import WalkForwardResult
        from src.evolution.backtest_validator import BacktestValidator

        # OOS 不达标：avg_oos_sharpe 为负 + IS→OOS gap 过大（过拟合）
        oos = WalkForwardResult(
            avg_oos_sharpe=-0.5,
            win_rate=0.3,
            avg_is_oos_return_gap=20.0,
            avg_is_oos_sharpe_drop=1.0,
        )
        r = BacktestValidator().validate(
            sharpe=1.2, total_return=0.5, max_dd=0.1, trades=50,
            oos_result=oos,
        )
        assert not r.oos_passed
        assert not r.passed  # OOS 不过 → 不直接合入
        assert r.oos_metrics.get("avg_oos_sharpe") == pytest.approx(-0.5)
        assert any("OOS" in f or "样本外" in f for f in r.failures)

    def test_oos_pass_allows_merge(self):
        from src.backtest.walkforward import WalkForwardResult
        from src.evolution.backtest_validator import BacktestValidator

        oos = WalkForwardResult(avg_oos_sharpe=0.8, win_rate=0.7)
        r = BacktestValidator().validate(
            sharpe=1.2, total_return=0.5, max_dd=0.1, trades=50,
            oos_result=oos,
        )
        assert r.oos_passed
        assert r.passed

    def test_validate_from_engine_result_accepts_oos(self):
        from src.backtest.walkforward import WalkForwardResult
        from src.evolution.backtest_validator import BacktestValidator
        from src.backtest.engine import BacktestResult

        engine = BacktestResult(
            strategy_name="S", start_date="2020-01-01", end_date="2021-01-01",
            initial_cash=1_000_000, final_value=1_200_000,
            total_return=0.2, annual_return=0.2, sharpe_ratio=1.0,
            max_drawdown=-0.1, win_rate=0.55, total_trades=30,
        )
        oos = WalkForwardResult(avg_oos_sharpe=-0.4)
        r = BacktestValidator().validate_from_engine_result(engine, oos_result=oos)
        assert not r.passed
        assert not r.oos_passed


class TestLifecycleOOSGate:
    def _manager(self):
        from src.evolution.lifecycle import LifecycleManager

        return LifecycleManager(":memory:")

    def test_no_oos_record_transitions_normally(self):
        from src.evolution.schema import LifecycleState, TransitionRequest, TransitionResult

        mgr = self._manager()
        lc = mgr.create(paper_id="p1", strategy_name="s1")
        mgr.update_backtest_result(lc.id, sharpe=1.2, total_return=0.5, max_dd=0.1, passed=True)
        resp = mgr.transition(TransitionRequest(
            lifecycle_id=lc.id, target_state=LifecycleState.CANDIDATE,
        ))
        assert resp.result == TransitionResult.OK

    def test_oos_failure_blocks_candidate(self):
        from src.evolution.schema import LifecycleState, TransitionRequest, TransitionResult

        mgr = self._manager()
        lc = mgr.create(paper_id="p2", strategy_name="s2")
        mgr.update_backtest_result(
            lc.id, sharpe=1.2, total_return=0.5, max_dd=0.1, passed=True,
            oos_passed=False, oos_note="OOS 样本外未达标",
        )
        resp = mgr.transition(TransitionRequest(
            lifecycle_id=lc.id, target_state=LifecycleState.CANDIDATE,
        ))
        assert resp.result == TransitionResult.CONDITION_NOT_MET
        assert "OOS" in resp.message or "样本外" in resp.message

    def test_oos_pass_allows_candidate(self):
        from src.evolution.schema import LifecycleState, TransitionRequest, TransitionResult

        mgr = self._manager()
        lc = mgr.create(paper_id="p3", strategy_name="s3")
        mgr.update_backtest_result(
            lc.id, sharpe=1.2, total_return=0.5, max_dd=0.1, passed=True,
            oos_passed=True, oos_note="OOS 达标",
        )
        resp = mgr.transition(TransitionRequest(
            lifecycle_id=lc.id, target_state=LifecycleState.CANDIDATE,
        ))
        assert resp.result == TransitionResult.OK

    def test_oos_status_query(self):
        mgr = self._manager()
        lc = mgr.create(paper_id="p4", strategy_name="s4")
        assert mgr.oos_status(lc.id) is None
        mgr.record_oos_validation(lc.id, oos_passed=False, note="过拟合")
        assert mgr.oos_status(lc.id)["oos_passed"] is False
