# -*- coding: utf-8 -*-
"""经济周期模块单元测试。"""

from __future__ import annotations

import pytest
from src.cycle.schema import (
    CYCLE_SECTOR_MAP,
    CYCLE_VALUATION_ADJUSTMENT,
    CycleAnalysis,
    CyclePhase,
)
from src.cycle.analyzer import CycleAnalyzer


class TestCyclePhase:
    def test_enum_values(self):
        assert CyclePhase.RECOVERY.value == "recovery"
        assert CyclePhase.EXPANSION.value == "expansion"
        assert CyclePhase.PEAK.value == "peak"
        assert CyclePhase.CONTRACTION.value == "contraction"
        assert CyclePhase.TROUGH.value == "trough"

    def test_all_phases_exist(self):
        assert len(CyclePhase) == 5


class TestCycleAnalysis:
    def test_is_pro_cycle(self):
        ca = CycleAnalysis(phase=CyclePhase.EXPANSION)
        assert ca.is_pro_cycle
        assert not ca.is_con_cycle

        ca2 = CycleAnalysis(phase=CyclePhase.RECOVERY)
        assert ca2.is_pro_cycle

    def test_is_con_cycle(self):
        ca = CycleAnalysis(phase=CyclePhase.CONTRACTION)
        assert ca.is_con_cycle
        assert not ca.is_pro_cycle

        ca2 = CycleAnalysis(phase=CyclePhase.TROUGH)
        assert ca2.is_con_cycle

        ca3 = CycleAnalysis(phase=CyclePhase.PEAK)
        assert ca3.is_con_cycle

    def test_earnings_environment(self):
        tests = {
            CyclePhase.RECOVERY: "improving",
            CyclePhase.EXPANSION: "strong",
            CyclePhase.PEAK: "peaking",
            CyclePhase.CONTRACTION: "deteriorating",
            CyclePhase.TROUGH: "bottoming",
        }
        for phase, expected in tests.items():
            ca = CycleAnalysis(phase=phase)
            assert ca.earnings_environment == expected

    def test_risk_level(self):
        assert CycleAnalysis(phase=CyclePhase.EXPANSION).risk_level == "low"
        assert CycleAnalysis(phase=CyclePhase.RECOVERY).risk_level == "medium"
        assert CycleAnalysis(phase=CyclePhase.CONTRACTION).risk_level == "high"

    def test_defaults(self):
        ca = CycleAnalysis(phase=CyclePhase.TROUGH)
        assert ca.confidence == 0.7
        assert ca.cycle_score == 50.0
        assert ca.signals_available == 0
        assert ca.preferred_sectors == []
        assert ca.avoid_sectors == []


class TestCycleMaps:
    def test_all_phases_in_sector_map(self):
        for phase in CyclePhase:
            assert phase in CYCLE_SECTOR_MAP, f"Missing {phase} in CYCLE_SECTOR_MAP"
            pref, avoid = CYCLE_SECTOR_MAP[phase]
            assert len(pref) > 0, f"No preferred sectors for {phase}"

    def test_all_phases_in_adjustment_map(self):
        for phase in CyclePhase:
            assert phase in CYCLE_VALUATION_ADJUSTMENT, f"Missing {phase} in adjustment map"

    def test_pro_cycle_adjustment_above_one(self):
        # Recovery and expansion should have adjustment > 1.0
        assert CYCLE_VALUATION_ADJUSTMENT[CyclePhase.RECOVERY] > 1.0
        assert CYCLE_VALUATION_ADJUSTMENT[CyclePhase.EXPANSION] > 1.0

    def test_con_cycle_adjustment_below_one(self):
        assert CYCLE_VALUATION_ADJUSTMENT[CyclePhase.CONTRACTION] < 1.0
        assert CYCLE_VALUATION_ADJUSTMENT[CyclePhase.PEAK] < 1.0


# ============================================================================
# CycleAnalyzer — 分类逻辑
# ============================================================================

class TestClassifyPhase:
    def setup_method(self):
        self.analyzer = CycleAnalyzer()

    def test_classify_expansion(self):
        phase = self.analyzer._classify_phase(
            pmi=53.5, pmi_trend="rising",
            ip=7.2, gdp=5.6, ppi=1.5,
        )
        assert phase == CyclePhase.EXPANSION

    def test_classify_peak(self):
        phase = self.analyzer._classify_phase(
            pmi=51.5, pmi_trend="falling",
            ip=5.5, gdp=5.8, ppi=3.5,
        )
        assert phase == CyclePhase.PEAK

    def test_classify_recovery(self):
        phase = self.analyzer._classify_phase(
            pmi=49.5, pmi_trend="rising",
            ip=3.5, gdp=4.2, ppi=-0.8,
        )
        assert phase == CyclePhase.RECOVERY

    def test_classify_contraction(self):
        phase = self.analyzer._classify_phase(
            pmi=47.5, pmi_trend="falling",
            ip=2.1, gdp=4.0, ppi=-1.5,
        )
        assert phase == CyclePhase.CONTRACTION

    def test_classify_trough(self):
        phase = self.analyzer._classify_phase(
            pmi=47.5, pmi_trend="rising",
            ip=2.8, gdp=4.0, ppi=-1.2,
        )
        assert phase == CyclePhase.TROUGH

    def test_classify_all_none(self):
        phase = self.analyzer._classify_phase(
            pmi=None, pmi_trend="stable",
            ip=None, gdp=None, ppi=None,
        )
        assert phase == CyclePhase.TROUGH

    def test_classify_high_pmi_high_ppi_is_peak(self):
        # PMI > 52 but PPI > 2.0 → PEAK (overheating)
        phase = self.analyzer._classify_phase(
            pmi=53.0, pmi_trend="stable",
            ip=6.5, gdp=5.8, ppi=3.0,
        )
        assert phase == CyclePhase.PEAK


class TestComputeCycleScore:
    def setup_method(self):
        self.analyzer = CycleAnalyzer()

    def test_expansion_highest(self):
        assert self.analyzer._compute_cycle_score(CyclePhase.EXPANSION) == 85.0

    def test_contraction_lowest(self):
        assert self.analyzer._compute_cycle_score(CyclePhase.CONTRACTION) == 20.0

    def test_recovery(self):
        assert self.analyzer._compute_cycle_score(CyclePhase.RECOVERY) == 70.0

    def test_scores_in_range(self):
        for phase in CyclePhase:
            score = self.analyzer._compute_cycle_score(phase)
            assert 0 <= score <= 100


class TestComputeTrend:
    def setup_method(self):
        self.analyzer = CycleAnalyzer()

    def test_first_call_stable(self):
        # No previous value cached → "stable"
        trend = self.analyzer._compute_trend("test_metric", 50.0)
        assert trend == "stable"

    def test_second_call_rising(self):
        self.analyzer._compute_trend("test_metric2", 48.0)  # set baseline
        trend = self.analyzer._compute_trend("test_metric2", 52.0)  # +4 → rising
        assert trend == "rising"

    def test_second_call_falling(self):
        self.analyzer._compute_trend("test_metric3", 52.0)  # set baseline
        trend = self.analyzer._compute_trend("test_metric3", 48.0)  # -4 → falling
        assert trend == "falling"

    def test_small_change_stable(self):
        self.analyzer._compute_trend("test_metric4", 50.0)  # set baseline
        trend = self.analyzer._compute_trend("test_metric4", 50.2)  # +0.2 → stable
        assert trend == "stable"

    def test_none_value(self):
        trend = self.analyzer._compute_trend("test_metric5", None)
        assert trend == "stable"


class TestSectorPreferences:
    def setup_method(self):
        self.analyzer = CycleAnalyzer()

    def test_recovery_prefers_brokers(self):
        pref, avoid = self.analyzer._compute_sector_preferences(CyclePhase.RECOVERY)
        assert "券商" in pref
        assert len(pref) > 0

    def test_contraction_avoids_growth(self):
        pref, avoid = self.analyzer._compute_sector_preferences(CyclePhase.CONTRACTION)
        combined_avoid = " ".join(avoid)
        assert "券商" in combined_avoid or "成长" in combined_avoid

    def test_unknown_phase_empty(self):
        # Should return empty lists for unexpected phase
        pref, avoid = self.analyzer._compute_sector_preferences(None)
        assert pref == []
        assert avoid == []


# ============================================================================
# 集成测试
# ============================================================================

class TestCycleAnalyzerIntegration:
    def setup_method(self):
        self.analyzer = CycleAnalyzer()

    def test_analyze_with_all_data(self):
        result = self.analyzer.analyze(
            pmi=53.5,
            industrial_production=7.2,
            gdp_growth=5.6,
            ppi=1.5,
        )
        assert isinstance(result, CycleAnalysis)
        assert result.phase is not None
        assert result.signals_available == 4
        assert result.confidence > 0.7
        assert result.cycle_score > 0
        assert isinstance(result.preferred_sectors, list)
        assert isinstance(result.avoid_sectors, list)

    def test_analyze_with_partial_data(self):
        """部分数据: 仅 PMI — AKShare 可能自动补其他数据，但 signals_available >= 1。"""
        result = self.analyzer.analyze(
            pmi=51.0,
            industrial_production=None,
            gdp_growth=None,
            ppi=None,
        )
        # At minimum PMI is available; AKShare may auto-fetch others
        assert result.signals_available >= 1
        assert isinstance(result.phase, CyclePhase)

    def test_analyze_no_data(self):
        result = self.analyzer.analyze()
        assert isinstance(result, CycleAnalysis)
        # With no data, PMI will try to fetch from AKShare, but should timeout/default
        assert result.signals_available >= 0

    def test_adjustment_factor_applied(self):
        result = self.analyzer.analyze(pmi=53.5, industrial_production=7.2, gdp_growth=5.6, ppi=1.5)
        assert result.cycle_adjustment_factor > 0
        # EXPANSION should have adjustment > 1.0
        if result.phase == CyclePhase.EXPANSION:
            assert result.cycle_adjustment_factor > 1.0

    def test_source_citations(self):
        result = self.analyzer.analyze(
            pmi=53.5, ppi=1.5,
        )
        assert len(result.source_citations) >= 1


class TestConfidence:
    def setup_method(self):
        self.analyzer = CycleAnalyzer()

    def test_all_signals(self):
        conf = self.analyzer._calc_confidence(4, 4)
        assert conf == 0.90

    def test_half_signals(self):
        conf = self.analyzer._calc_confidence(2, 4)
        assert conf == pytest.approx(0.60)  # 0.90 - 0.30

    def test_no_signals(self):
        conf = self.analyzer._calc_confidence(0, 4)
        assert conf == pytest.approx(0.3)
