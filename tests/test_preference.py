# -*- coding: utf-8 -*-
"""投资者偏好系统测试。"""

from __future__ import annotations

import os
import tempfile

import pytest

from src.learner.preference.adapter import (
    resolve_competence_penalty,
    resolve_macro_cap_multiplier,
    resolve_position_limits,
    resolve_rule_filter,
    resolve_weights,
)
from src.learner.preference.loader import InvestorPreferenceLoader
from src.learner.preference.model import (
    CircleOfCompetence,
    InvestmentGoal,
    InvestorPreference,
    InvestorTier,
    PositionLimits,
    RiskProfile,
    ScoreWeights,
    TradingStyle,
)


# ------------------------------------------------------------------
# Model
# ------------------------------------------------------------------


class TestInvestorPreferenceModel:
    """测试投资者偏好数据模型。"""

    def test_default_construction(self):
        prefs = InvestorPreference()
        assert prefs.risk_profile == RiskProfile.BALANCED
        assert prefs.investment_goal == InvestmentGoal.ABSOLUTE_RETURN
        assert prefs.trading_style == TradingStyle.MIXED
        assert prefs.tier == InvestorTier.BEGINNER
        assert prefs.benchmark == "沪深300"
        assert prefs.investment_horizon == "3-5年"

    def test_position_limits_defaults(self):
        limits = PositionLimits()
        assert limits.max_single_pct == 0.20
        assert limits.max_sector_pct == 0.40
        assert limits.gem_discount == 0.80

    def test_to_dict_roundtrip(self):
        """to_dict() 后 from_dict() 应恢复原样。"""
        prefs = InvestorPreference(
            risk_profile=RiskProfile.CONSERVATIVE,
            investment_goal=InvestmentGoal.CASH_FLOW,
            tier=InvestorTier.PRO,
            score_weights=ScoreWeights(fundamental=0.55, technical=0.15),
        )
        d = prefs.to_dict()
        restored = InvestorPreference.from_dict(d)
        assert restored.risk_profile == prefs.risk_profile
        assert restored.investment_goal == prefs.investment_goal
        assert restored.tier == prefs.tier
        assert restored.score_weights.fundamental == 0.55
        assert restored.score_weights.technical == 0.15

    def test_to_dict_roundtrip_handles_legacy_limits_key(self):
        """from_dict 兼容 'limits' 和 'position_limits' 两种键名。"""
        d = {"risk_profile": "aggressive", "limits": {"max_single_pct": 0.25}}
        prefs = InvestorPreference.from_dict(d)
        assert prefs.risk_profile == RiskProfile.AGGRESSIVE
        assert prefs.position_limits.max_single_pct == 0.25

    def test_enum_values_serializable(self):
        """枚举 .value 在 YAML 中可序列化。"""
        prefs = InvestorPreference(risk_profile=RiskProfile.AGGRESSIVE)
        d = prefs.to_dict()
        assert d["risk_profile"] == "aggressive"

    def test_score_weights_defaults(self):
        w = ScoreWeights()
        assert w.fundamental is None
        assert w.technical is None
        assert w.to_dict() == {
            "fundamental": None, "technical": None,
            "macro": None, "sector": None, "sentiment": None,
        }

    def test_circle_of_competence_from_none(self):
        coc = CircleOfCompetence.from_dict(None)
        assert coc.industries == {"消费": 3, "新能源": 2, "科技": 2}

    def test_circle_of_competence_from_dict(self):
        d = {"消费": 5, "医药": 4}
        coc = CircleOfCompetence.from_dict(d)
        assert coc.industries["消费"] == 5
        assert coc.industries["医药"] == 4


# ------------------------------------------------------------------
# Loader
# ------------------------------------------------------------------


class TestInvestorPreferenceLoader:
    """测试 YAML 持久化加载器。"""

    def test_load_missing_file(self):
        """缺文件时返回默认值。"""
        loader = InvestorPreferenceLoader("/tmp/nonexistent_prefs.yaml")
        prefs = loader.load()
        assert prefs.risk_profile == RiskProfile.BALANCED

    def test_load_and_save(self):
        """写入 YAML，读回，验证相等性。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            path = f.name

        try:
            loader = InvestorPreferenceLoader(path)
            original = InvestorPreference(
                risk_profile=RiskProfile.AGGRESSIVE,
                investment_goal=InvestmentGoal.RELATIVE_RETURN,
                tier=InvestorTier.INTERMEDIATE,
                benchmark="中证500",
            )
            loader.save(original)
            loaded = loader.load()
            assert loaded.risk_profile == original.risk_profile
            assert loaded.benchmark == "中证500"
            assert loaded.tier == InvestorTier.INTERMEDIATE
        finally:
            os.unlink(path)

    def test_load_corrupted_yaml(self):
        """无效 YAML → 静默回退到默认值。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("{invalid: [yaml: ::: corrupted}")
            path = f.name

        try:
            loader = InvestorPreferenceLoader(path)
            prefs = loader.load()
            # 应回退到默认值而非崩溃
            assert prefs.risk_profile == RiskProfile.BALANCED
        finally:
            os.unlink(path)

    def test_reset(self):
        """reset() 写入并返回默认值。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            path = f.name

        try:
            loader = InvestorPreferenceLoader(path)
            loader.save(InvestorPreference(
                risk_profile=RiskProfile.AGGRESSIVE,
            ))
            prefs = loader.reset()
            assert prefs.risk_profile == RiskProfile.BALANCED
            # 重新加载也应默认为 balanced
            reloaded = loader.load()
            assert reloaded.risk_profile == RiskProfile.BALANCED
        finally:
            os.unlink(path)

    def test_summary_format(self):
        """检查人类可读的摘要输出。"""
        loader = InvestorPreferenceLoader()
        prefs = InvestorPreference()
        s = loader.summary(prefs)
        assert "balanced" in s
        assert "absolute_return" in s
        assert "投资者偏好画像" in s

    def test_load_empty_yaml(self):
        """空 YAML → 返回默认值。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("")
            path = f.name

        try:
            loader = InvestorPreferenceLoader(path)
            prefs = loader.load()
            assert prefs.risk_profile == RiskProfile.BALANCED
        finally:
            os.unlink(path)


# ------------------------------------------------------------------
# Adapter
# ------------------------------------------------------------------


class TestPreferenceAdapter:
    """测试偏好适配器映射逻辑。"""

    def _make_prefs(
        self,
        risk=RiskProfile.BALANCED,
        goal=InvestmentGoal.ABSOLUTE_RETURN,
        tier=InvestorTier.BEGINNER,
    ):
        return InvestorPreference(risk_profile=risk, investment_goal=goal, tier=tier)

    def test_resolve_weights_balanced(self):
        """balanced + absolute_return → 默认权重。"""
        prefs = self._make_prefs()
        w = resolve_weights(prefs)
        assert abs(sum(w.values()) - 1.0) < 0.01
        assert w["fundamental"] == 0.40
        assert w["sentiment"] == 0.15

    def test_resolve_weights_conservative(self):
        """conservative → 权重向基本面偏移。"""
        prefs = self._make_prefs(risk=RiskProfile.CONSERVATIVE)
        w = resolve_weights(prefs)
        assert w["fundamental"] >= 0.45
        assert w["sentiment"] <= 0.15

    def test_resolve_weights_aggressive(self):
        """aggressive → 权重向动量偏移。"""
        prefs = self._make_prefs(risk=RiskProfile.AGGRESSIVE)
        w = resolve_weights(prefs)
        assert w["technical"] >= 0.25
        assert w["fundamental"] <= 0.35

    def test_resolve_weights_cash_flow(self):
        """cash_flow → 极致基本面。"""
        prefs = self._make_prefs(goal=InvestmentGoal.CASH_FLOW)
        w = resolve_weights(prefs)
        assert w["fundamental"] >= 0.50

    def test_resolve_weights_with_override(self):
        """显式覆盖优先于预设。"""
        prefs = self._make_prefs()
        prefs.score_weights = ScoreWeights(
            fundamental=0.60, technical=None,
            macro=None, sector=None, sentiment=None,
        )
        w = resolve_weights(prefs)
        assert w["fundamental"] == 0.60

    def test_all_weight_presets_sum_to_one(self):
        """所有权重预设总和为 1.0。"""
        from src.learner.preference.adapter import WEIGHT_PRESETS
        for key, w in WEIGHT_PRESETS.items():
            assert abs(sum(w.values()) - 1.0) < 0.01, f"{key} weights sum to {sum(w.values())}"

    def test_resolve_rule_filter_beginner(self):
        """BEGINNER → None（全部启用）。"""
        prefs = self._make_prefs(tier=InvestorTier.BEGINNER)
        assert resolve_rule_filter(prefs) is None

    def test_resolve_rule_filter_intermediate(self):
        """INTERMEDIATE → 返回规则子集。"""
        prefs = self._make_prefs(tier=InvestorTier.INTERMEDIATE)
        result = resolve_rule_filter(prefs)
        assert result is not None
        assert "r006" in result   # ST 否决
        assert "r025" in result   # 单笔止损

    def test_resolve_rule_filter_pro(self):
        """PRO → 仅核心下行保护。"""
        prefs = self._make_prefs(tier=InvestorTier.PRO)
        result = resolve_rule_filter(prefs)
        assert result is not None
        assert "r001" in result
        assert "r025" in result

    def test_resolve_rule_filter_manual_override(self):
        """enabled_rules 列表覆盖层级。"""
        prefs = self._make_prefs(tier=InvestorTier.PRO)
        prefs.enabled_rules = ["r001", "r006"]
        result = resolve_rule_filter(prefs)
        assert result == {"r001", "r006"}
        # PRO 核心规则 r025 不在手动列表中 → 不应出现
        assert "r025" not in result

    def test_resolve_position_limits(self):
        prefs = self._make_prefs()
        limits = resolve_position_limits(prefs)
        assert limits["single_stock_cap"] == 0.20
        assert limits["sector_cap"] == 0.40
        assert limits["max_drawdown"] == -0.15
        assert limits["stop_loss"] == -0.02

    def test_resolve_macro_cap_multiplier(self):
        assert resolve_macro_cap_multiplier(
            self._make_prefs(risk=RiskProfile.CONSERVATIVE)
        ) == 0.7
        assert resolve_macro_cap_multiplier(
            self._make_prefs(risk=RiskProfile.BALANCED)
        ) == 1.0
        assert resolve_macro_cap_multiplier(
            self._make_prefs(risk=RiskProfile.AGGRESSIVE)
        ) == 1.2

    def test_resolve_competence_penalty_known(self):
        """高熟悉度行业 → 无惩罚。"""
        prefs = self._make_prefs()
        prefs.circle_of_competence = CircleOfCompetence(
            industries={"消费": 4, "医疗": 3}
        )
        assert resolve_competence_penalty(prefs, "消费") == 1.0
        assert resolve_competence_penalty(prefs, "医疗") == 1.0

    def test_resolve_competence_penalty_unknown(self):
        """不在能力圈 → 0.85。"""
        prefs = self._make_prefs()
        prefs.circle_of_competence = CircleOfCompetence(
            industries={"消费": 4}
        )
        assert resolve_competence_penalty(prefs, "军工") == 0.85

    def test_resolve_competence_penalty_low(self):
        """熟悉度 1 → 0.70。"""
        prefs = self._make_prefs()
        prefs.circle_of_competence = CircleOfCompetence(
            industries={"消费": 4, "新能源": 1}
        )
        assert resolve_competence_penalty(prefs, "新能源") == 0.70

    def test_resolve_competence_penalty_empty(self):
        """空能力圈 → 无惩罚。"""
        prefs = self._make_prefs()
        prefs.circle_of_competence = CircleOfCompetence(industries={})
        assert resolve_competence_penalty(prefs, "任何行业") == 1.0


# ------------------------------------------------------------------
# Pipeline Integration
# ------------------------------------------------------------------


class TestPreferencePipelineIntegration:
    """测试偏好系统与管道的集成。"""

    def test_orchestrator_handles_default_prefs(self):
        """Orchestrator 加载默认偏好不崩溃。"""
        from src.routing.orchestrator import Orchestrator
        orch = Orchestrator()
        # _get_investor_prefs 应返回默认值或 None
        prefs = orch._get_investor_prefs()
        # 只要不抛异常就算通过
        assert prefs is not None

    def test_doctrine_with_enabled_rules(self):
        """传递 enabled_rules 不崩溃。"""
        from src.doctrine.checker import DoctrineChecker
        checker = DoctrineChecker()
        result = checker.check(
            symbol="000001",
            context={"stock_name": "平安银行"},
            enabled_rules={"r001", "r002"},
        )
        assert result.passed is True

    def test_l2_judge_with_weights_override(self):
        """传递 weights_override 不改变接口兼容性。"""
        from src.routing.l1_analyze import AnalysisReport
        from src.routing.l2_judge import L2Judge
        judge = L2Judge()
        report = AnalysisReport(
            symbol="600519", name="贵州茅台",
            value_score=70, quality_score=65, momentum_score=55,
            macro_score=60,
        )
        verdict = judge.judge(report, weights_override={"fundamental": 0.50})
        assert verdict is not None
        assert 0 <= verdict.score <= 100

    def test_l3_with_preference_params(self):
        """传递 position_limits 和 risk_multiplier 不崩溃。"""
        from src.routing.l2_judge import Verdict
        from src.routing.l3_trade import L3Trader
        trader = L3Trader()
        verdict = Verdict(symbol="600519", score=80, confidence=0.7)
        signal = trader.generate_signal(
            verdict,
            position_limits={"single_stock_cap": 0.15, "gem_discount": 0.75},
            risk_multiplier=0.7,
        )
        assert signal.target_weight <= 0.15

    def test_l4_with_position_limits(self):
        """传递 position_limits 覆盖类级常量。"""
        from src.routing.l3_trade import TradeSignal
        from src.routing.l4_risk import L4RiskOfficer
        risk_officer = L4RiskOfficer()
        signal = TradeSignal(
            symbol="600519", action="OPEN", target_weight=0.25,
        )
        result = risk_officer.check(
            signal,
            position_limits={"single_stock_cap": 0.10},
        )
        assert result.adjusted_weight <= 0.10
        assert len(result.violations) >= 1
