# -*- coding: utf-8 -*-
"""Phase 2 模块测试: 军规、路由、情绪、博弈论完整模块。"""

from __future__ import annotations

import pytest


# ── Doctrine ──

class TestDoctrine:
    def test_all_38_rules(self):
        from src.doctrine.rules import MILITARY_RULES
        assert len(MILITARY_RULES) == 38

    def test_rule_categories(self):
        from src.doctrine.rules import MILITARY_RULES, Severity
        blocks = [r for r in MILITARY_RULES if r.severity == Severity.BLOCK]
        warns = [r for r in MILITARY_RULES if r.severity == Severity.WARN]
        infos = [r for r in MILITARY_RULES if r.severity == Severity.INFO]
        assert len(blocks) >= 10, "至少 10 条 block 级军规"
        assert len(warns) >= 10
        assert len(infos) >= 2

    def test_block_rules_block_trading(self):
        from src.doctrine.checker import DoctrineChecker
        checker = DoctrineChecker()
        # ST 股票应被拦截
        result = checker.check("600000", {"stock_name": "*ST 华泽"})
        assert not result.passed
        assert len(result.blocked_by) >= 1

    def test_normal_stock_passes(self):
        from src.doctrine.checker import DoctrineChecker
        checker = DoctrineChecker()
        result = checker.check("600519", {"stock_name": "贵州茅台"})
        assert result.passed

    def test_system_meltdown(self):
        from src.doctrine.checker import DoctrineChecker
        checker = DoctrineChecker()
        result = checker.check("600519", {"rolling_3m_winrate": 0.35})
        assert not result.passed


# ── 准入检查 ──

class TestAdmission:
    def test_st_rejected(self):
        from src.routing.admission import AdmissionCheck
        gate = AdmissionCheck()
        result = gate.check("000000", "*ST 华泽")
        assert result.status.value == "REJECTED"

    def test_normal_accepted(self):
        from src.routing.admission import AdmissionCheck
        gate = AdmissionCheck()
        result = gate.check("600519", "贵州茅台")
        assert result.status.value == "ACCEPTED"

    def test_ipo_rejected(self):
        from src.routing.admission import AdmissionCheck
        gate = AdmissionCheck()
        result = gate.check("688981", "中芯国际", {"listing_days": 30})
        assert result.status.value == "REJECTED"


# ── 裁决 ──

class TestVerdict:
    def test_high_score_buy(self):
        from src.routing.diagnosis import DiagnosisEngine
        from src.routing.verdict import VerdictEngine
        analyzer = DiagnosisEngine()
        report = analyzer.analyze("600519", "茅台",
                                   {"pe_percentile": 20, "northbound": 1},
                                   [{"roe": 25}],
                                   {"pmi": 52, "erp": 5},
                                   {"level": "NORMAL"})
        judge = VerdictEngine()
        verdict = judge.judge(report)
        assert verdict.score >= 60
        assert verdict.recommendation in ("BUY", "ADD")

    def test_low_confidence_blocked(self):
        from src.routing.diagnosis import DiagnosisReport
        from src.routing.verdict import VerdictEngine
        report = DiagnosisReport(symbol="000001", name="测试",
                                 value_score=30, quality_score=30,
                                 momentum_score=30, macro_score=30)
        judge = VerdictEngine()
        verdict = judge.judge(report)
        assert verdict.confidence < 0.7


# ── 风控 ──

class TestRiskControl:
    def test_position_cap(self):
        from src.routing.positioning import PositioningEngine, TradeSignal
        from src.routing.risk_control import RiskControlEngine
        signal = TradeSignal(symbol="600519", action="OPEN", target_weight=0.30)
        officer = RiskControlEngine()
        risk = officer.check(signal)
        assert risk.adjusted_weight <= 0.20

    def test_black_swan(self):
        from src.routing.positioning import TradeSignal
        from src.routing.risk_control import RiskControlEngine
        signal = TradeSignal(symbol="600519", action="OPEN", target_weight=0.10)
        officer = RiskControlEngine()
        risk = officer.check(signal, market={"hs300_change_pct": -0.06})
        assert risk.adjusted_weight == 0.0


# ── Sentiment ──

class TestSentiment:
    def test_panic_detection(self):
        from src.sentiment.signals import SentimentDetector
        detector = SentimentDetector()
        sentiment = detector.detect_market(
            advance_decline=0.2, limit_down=60,
            volume_ratio=2.5, northbound=-8.0, margin_change=-50
        )
        assert sentiment.level.value in ("PANIC", "EXTREME_PANIC")

    def test_normal_market(self):
        from src.sentiment.signals import SentimentDetector
        detector = SentimentDetector()
        sentiment = detector.detect_market()
        assert sentiment.level.value == "NORMAL"


class TestPanicArb:
    def test_overreaction_signal(self):
        from src.sentiment.panic_arb import PanicArbEngine
        engine = PanicArbEngine()
        event = {
            "type": "policy", "is_fundamental": False,
            "description": "突发监管政策", "eps_impact_pct": -3,
            "actual_drop_pct": -10, "institution_clarified": True,
            "northbound_inflow": True,
        }
        signal = engine.analyze(event)
        assert signal.level.value == "OVERREACTION"
        assert signal.suggested_position_pct <= 0.25

    def test_fundamental_not_arb(self):
        from src.sentiment.panic_arb import PanicArbEngine
        engine = PanicArbEngine()
        event = {"is_fundamental": True, "type": "earnings_miss"}
        signal = engine.analyze(event)
        assert signal.level.value == "NONE"


# ── Game Theory: Players ──

class TestPlayers:
    def test_seven_profiles(self):
        from src.game_theory.players import PLAYER_PROFILES
        assert len(PLAYER_PROFILES) == 7

    def test_all_have_patterns(self):
        from src.game_theory.players import PLAYER_PROFILES
        for p in PLAYER_PROFILES:
            assert len(p.signature_patterns) >= 2
            assert len(p.data_sources) >= 1


# ── Game Theory: Playbooks ──

class TestPlaybooks:
    def test_three_playbooks(self):
        from src.game_theory.playbooks import TOP_3_PLAYBOOKS
        assert len(TOP_3_PLAYBOOKS) == 3

    def test_all_hypothesis(self):
        from src.game_theory.playbooks import TOP_3_PLAYBOOKS
        for pb in TOP_3_PLAYBOOKS:
            assert pb.evidence_level == "HYPOTHESIS"
            assert len(pb.execution_pattern) >= 3
            assert len(pb.exit_conditions) >= 2


# ── Game Theory: Comparative ──

class TestComparative:
    def test_eight_dimensions(self):
        from src.game_theory.comparative import MARKET_COMPARISONS
        assert len(MARKET_COMPARISONS) == 8

    def test_asymmetry_report(self):
        from src.game_theory.comparative import asymmetry_report
        r = asymmetry_report(20)
        assert "50" in r  # mentions threshold


# ── Orchestrator ──

class TestOrchestrator:
    def test_quick_check_passes(self):
        from src.routing.orchestrator import Orchestrator
        orch = Orchestrator()
        result = orch.quick_check("600519", "贵州茅台")
        assert result.passed

    def test_st_blocked(self):
        from src.routing.orchestrator import Orchestrator
        orch = Orchestrator()
        result = orch.quick_check("000000", "*ST 华泽")
        assert not result.passed
        assert len(result.blocked_by) >= 1


# ── Admission ──

class TestAdmission:
    """准入检查：低流动性、ST、次新股、涨跌停、停牌过滤。"""

    def test_low_liquidity_rejected(self):
        """日成交额 < 5000万 → REJECTED。"""
        from src.routing.admission import AdmissionCheck
        c = AdmissionCheck()
        r = c.check("000001", "平安银行", {"avg_daily_volume": 3e7})  # 3000万
        assert r.status.value == "REJECTED"
        assert "流动性不足" in r.flags

    def test_sufficient_liquidity_passes(self):
        """日成交额 >= 5000万 → ACCEPTED。"""
        from src.routing.admission import AdmissionCheck
        c = AdmissionCheck()
        r = c.check("000001", "平安银行", {"avg_daily_volume": 8e7})  # 8000万
        assert r.status.value == "ACCEPTED"

    def test_missing_liquidity_data_passes(self):
        """无成交额数据时使用默认值(10亿)放行，不误杀。"""
        from src.routing.admission import AdmissionCheck
        c = AdmissionCheck()
        r = c.check("000001", "平安银行", {})
        assert r.status.value == "ACCEPTED"

    def test_liquidity_at_boundary(self):
        """日成交额恰好 5000万 → ACCEPTED (>= 条件)。"""
        from src.routing.admission import AdmissionCheck
        c = AdmissionCheck()
        r = c.check("000001", "平安银行", {"avg_daily_volume": 5e7})
        assert r.status.value == "ACCEPTED"


# ── Game Theory: Price Impact ──

class TestPriceImpact:
    def test_six_profiles(self):
        from src.game_theory.price_impact import PRICE_IMPACT_PROFILES
        assert len(PRICE_IMPACT_PROFILES) == 6
