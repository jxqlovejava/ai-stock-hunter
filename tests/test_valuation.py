# -*- coding: utf-8 -*-
"""估值模块单元测试。"""

from __future__ import annotations

import pytest
from src.valuation.schema import ValuationPhase, ValuationResult, ValuationSubScores
from src.valuation.analyzer import ValuationAnalyzer, _ValuationWeights


class TestValuationPhase:
    def test_enum_values(self):
        assert ValuationPhase.DEEP_VALUE.value == "deep_value"
        assert ValuationPhase.FAIR_VALUE.value == "fair_value"
        assert ValuationPhase.PREMIUM.value == "premium"
        assert ValuationPhase.BUBBLE.value == "bubble"

    def test_all_phases_exist(self):
        assert len(ValuationPhase) == 4


class TestValuationSubScores:
    def test_default_construction(self):
        scores = ValuationSubScores()
        assert scores.pe_percentile_score == 50.0
        assert scores.pb_roe_match_score == 50.0
        assert scores.signals_available == 0
        assert scores.confidence == 0.7

    def test_full_values(self):
        scores = ValuationSubScores(
            pe_percentile_score=80.0,
            peg_score=60.0,
            signals_available=5,
        )
        assert scores.pe_percentile_score == 80.0
        assert scores.peg_score == 60.0
        assert scores.signals_available == 5


class TestValuationResult:
    def test_is_cheap(self):
        r = ValuationResult(symbol="000001", name="测试", composite_score=85.0)
        assert r.is_cheap
        assert not r.is_expensive

    def test_is_expensive(self):
        r = ValuationResult(symbol="000001", name="测试", composite_score=15.0)
        assert r.is_expensive
        assert not r.is_cheap

    def test_neither(self):
        r = ValuationResult(symbol="000001", name="测试", composite_score=50.0)
        assert not r.is_cheap
        assert not r.is_expensive

    def test_valuation_context_formatting(self):
        r = ValuationResult(
            symbol="600519", name="茅台",
            composite_score=60.0, pe_ttm=25.5, pb=8.2,
            phase=ValuationPhase.FAIR_VALUE,
        )
        ctx = r.valuation_context
        assert "PE=25.5" in ctx
        assert "PB=8.20" in ctx
        assert "60" in ctx

    def test_valuation_context_no_data(self):
        r = ValuationResult(symbol="000001", name="测试")
        ctx = r.valuation_context
        assert "N/A" in ctx

    def test_data_completeness(self):
        r = ValuationResult(symbol="000001", name="测试", pe_ttm=10.0, pb=1.5, pe_percentile=30.0)
        assert r.data_completeness == 0.75  # 3 of 4 (peg missing)

    def test_default_construction(self):
        r = ValuationResult(symbol="000001", name="测试")
        assert r.composite_score == 50.0
        assert r.phase == ValuationPhase.FAIR_VALUE
        assert r.peg_ratio is None


class TestValuationWeights:
    def test_default_total_is_one(self):
        w = _ValuationWeights()
        assert abs(w.total - 1.0) < 1e-6

    def test_normalize_already_normalized(self):
        w = _ValuationWeights()
        result = w.normalize()
        assert abs(result.total - 1.0) < 1e-6

    def test_normalize(self):
        w = _ValuationWeights(pe_percentile=0.5, industry_relative=0.5, pb_roe_match=0.5, peg=0.5, dividend_yield=0.5)
        result = w.normalize()
        assert abs(result.total - 1.0) < 1e-6


# ============================================================================
# ValuationAnalyzer — 评分方法
# ============================================================================

class TestScorePEPercentile:
    def setup_method(self):
        self.analyzer = ValuationAnalyzer()

    def test_low_percentile_is_high_score(self):
        # PE at 10th percentile → should be very cheap
        score = self.analyzer._score_pe_percentile(10)
        assert score == 90.0

    def test_high_percentile_is_low_score(self):
        # PE at 90th percentile → very expensive
        score = self.analyzer._score_pe_percentile(90)
        assert score == 10.0

    def test_mid_percentile(self):
        score = self.analyzer._score_pe_percentile(50)
        assert score == 50.0

    def test_missing_data(self):
        score = self.analyzer._score_pe_percentile(None)
        assert score == 50.0


class TestScoreIndustryRelative:
    def setup_method(self):
        self.analyzer = ValuationAnalyzer()

    def test_cheaper_than_industry(self):
        # Stock PE=15, industry median=25 → discount = 40%
        score = self.analyzer._score_industry_relative(15.0, 25.0)
        assert score > 50.0

    def test_expensive_vs_industry(self):
        # Stock PE=30, industry median=20 → premium
        score = self.analyzer._score_industry_relative(30.0, 20.0)
        assert score < 50.0

    def test_equal_to_industry(self):
        score = self.analyzer._score_industry_relative(20.0, 20.0)
        assert score == 50.0

    def test_no_industry_data(self):
        score = self.analyzer._score_industry_relative(20.0, None)
        assert score == 50.0

    def test_no_stock_pe(self):
        score = self.analyzer._score_industry_relative(None, 25.0)
        assert score == 50.0


class TestScorePBROE:
    def setup_method(self):
        self.analyzer = ValuationAnalyzer()

    def test_justified_values(self):
        # ROE=15%, cost_of_equity=10% → justified PB=1.5
        # Actual PB=1.5 → close to justified → high score
        score, justified = self.analyzer._score_pb_roe(pb=1.5, roe=15.0)
        assert justified is not None
        assert abs(justified - 1.5) < 0.1
        assert score >= 70.0

    def test_overvalued_pb_roe(self):
        # Actual PB >> justified → low score
        score, _ = self.analyzer._score_pb_roe(pb=5.0, roe=10.0)
        assert score < 50.0

    def test_undervalued_pb_roe(self):
        # Actual PB=0.8, ROE=20% → justified=2.0, deviation=0.6
        # Need to test it scores reasonably (not penalized for being too far)
        score, justified = self.analyzer._score_pb_roe(pb=0.8, roe=20.0)
        assert justified is not None
        assert justified > 1.0  # justified PB should be reasonable
        assert score >= 30  # not severely penalized

    def test_negative_roe(self):
        score, justified = self.analyzer._score_pb_roe(pb=2.0, roe=-5.0)
        assert score == 50.0
        assert justified is None

    def test_missing_pb(self):
        score, _ = self.analyzer._score_pb_roe(pb=None, roe=15.0)
        assert score == 50.0


class TestScorePEG:
    def setup_method(self):
        self.analyzer = ValuationAnalyzer()

    def test_low_peg_is_high_score(self):
        # P/E=15, growth=20% → PEG=0.75 → cheap relative to growth
        score, peg = self.analyzer._score_peg(pe_ttm=15.0, earnings_growth=20.0)
        assert peg is not None
        assert peg < 1.0
        assert score >= 70

    def test_high_peg_is_low_score(self):
        # P/E=30, growth=5% → PEG=6 → expensive
        score, peg = self.analyzer._score_peg(pe_ttm=30.0, earnings_growth=5.0)
        assert peg is not None
        assert peg > 2.0
        assert score < 50.0

    def test_peg_around_one(self):
        score, _ = self.analyzer._score_peg(pe_ttm=20.0, earnings_growth=22.0)
        assert 80 >= score >= 50

    def test_negative_pe(self):
        score, peg = self.analyzer._score_peg(pe_ttm=-10.0, earnings_growth=15.0)
        assert score == 50.0
        assert peg is None

    def test_no_growth_data(self):
        score, peg = self.analyzer._score_peg(pe_ttm=20.0, earnings_growth=None)
        assert score == 50.0
        assert peg is None


class TestScoreDividendYield:
    def setup_method(self):
        self.analyzer = ValuationAnalyzer()

    def test_high_yield(self):
        score = self.analyzer._score_dividend_yield(4.5)
        assert score >= 80

    def test_moderate_yield(self):
        score = self.analyzer._score_dividend_yield(2.0)
        assert score == 70.0

    def test_low_yield(self):
        score = self.analyzer._score_dividend_yield(0.3)
        assert score == 40.0

    def test_no_dividend(self):
        score = self.analyzer._score_dividend_yield(None)
        assert score == 40.0


class TestClassifyPhase:
    def setup_method(self):
        self.analyzer = ValuationAnalyzer()

    def test_deep_value(self):
        phase = self.analyzer._classify_phase(composite_score=85.0, pe_percentile=10.0)
        assert phase == ValuationPhase.DEEP_VALUE

    def test_bubble(self):
        # PE > 80th + high PB → bubble
        phase = self.analyzer._classify_phase(composite_score=15.0, pe_percentile=90.0, pb=8.0, pb_percentile=95.0)
        assert phase == ValuationPhase.BUBBLE

    def test_premium(self):
        phase = self.analyzer._classify_phase(composite_score=25.0, pe_percentile=70.0)
        assert phase == ValuationPhase.PREMIUM

    def test_fair_value(self):
        phase = self.analyzer._classify_phase(composite_score=50.0, pe_percentile=45.0)
        assert phase == ValuationPhase.FAIR_VALUE


# ============================================================================
# 集成测试
# ============================================================================

class TestValuationAnalyzerIntegration:
    def setup_method(self):
        self.analyzer = ValuationAnalyzer()

    def test_analyze_full(self):
        """完整分析流程 — 所有数据可用。"""
        result = self.analyzer.analyze(
            symbol="600519",
            name="贵州茅台",
            pe_ttm=25.5,
            pb=8.2,
            pe_percentile=35.0,
            roe=28.5,
            earnings_growth=15.0,
            dividend_yield=1.5,
            industry_pe_median=30.0,
        )
        assert isinstance(result, ValuationResult)
        assert 0 <= result.composite_score <= 100
        assert result.phase is not None
        assert result.sub_scores.signals_available >= 4
        assert result.source_citations

    def test_analyze_minimal(self):
        """只有 PE 分位 — 回退到部分可用。"""
        result = self.analyzer.analyze(
            symbol="000001",
            name="平安银行",
            pe_percentile=60.0,
        )
        assert isinstance(result, ValuationResult)
        assert result.composite_score <= 100
        assert result.sub_scores.signals_available < 5
        # PE at 60th percentile → score = 40
        assert result.sub_scores.pe_percentile_score == 40.0

    def test_analyze_no_data(self):
        """无数据 — 返回默认值（股息率为0时权重10%导致约49分）。"""
        result = self.analyzer.analyze(symbol="000001", name="测试")
        assert 45.0 <= result.composite_score <= 55.0
        assert result.phase == ValuationPhase.FAIR_VALUE

    def test_source_citations_built(self):
        result = self.analyzer.analyze(
            symbol="600519", name="茅台",
            pe_percentile=35.0, pe_ttm=25.5, pb=8.2,
            roe=28.5, earnings_growth=15.0,
        )
        assert len(result.source_citations) >= 2


class TestSubConfidence:
    def setup_method(self):
        self.analyzer = ValuationAnalyzer()

    def test_all_signals_present(self):
        conf = self.analyzer._calc_sub_confidence(5, 5)
        assert conf == 0.95

    def test_two_signals_missing(self):
        conf = self.analyzer._calc_sub_confidence(3, 5)
        assert conf == pytest.approx(0.65)  # 0.95 - 0.3

    def test_all_signals_missing(self):
        conf = self.analyzer._calc_sub_confidence(0, 5)
        assert conf == pytest.approx(0.3)  # minimum floor
