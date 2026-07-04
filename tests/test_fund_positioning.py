"""Tests for fund positioning and crowding analysis."""

import pytest
from src.game_theory.fund_positioning import (
    FundPositioningAnalyzer,
    FundCrowdingSignal,
)


class TestFundCrowdingSignal:
    def test_default_construction(self):
        s = FundCrowdingSignal()
        assert s.crowding_score == 50
        assert s.risk_level == "low"
        assert s.new_fund_issuance_trend == "stable"
        assert s.recommended_action == "neutral"

    def test_crowded_signal(self):
        s = FundCrowdingSignal(
            crowding_score=75,
            risk_level="high",
            recommended_action="avoid_overcrowded",
            crowded_sectors=["新能源", "半导体"],
        )
        assert s.risk_level == "high"
        assert len(s.crowded_sectors) == 2


class TestFundPositioningAnalyzer:
    def setup_method(self):
        self.analyzer = FundPositioningAnalyzer()

    def test_compute_crowding_score_low(self):
        s = FundCrowdingSignal(
            top_holdings_overlap_ratio=0.3,
            new_fund_issuance_trend="rising",
            estimated_positioning_pct=78,
        )
        score = self.analyzer._compute_crowding_score(s)
        # Low overlap + new money flowing in + low positioning → low crowding
        assert score <= 45

    def test_compute_crowding_score_high(self):
        s = FundCrowdingSignal(
            top_holdings_overlap_ratio=0.8,
            new_fund_issuance_trend="falling",
            estimated_positioning_pct=90,
        )
        score = self.analyzer._compute_crowding_score(s)
        # High overlap + no new money + high positioning → high crowding
        assert score >= 65

    def test_compute_crowding_score_sector(self):
        s = FundCrowdingSignal(
            top_holdings_overlap_ratio=0.4,
            sector_crowding={"新能源": 0.25},
            new_fund_issuance_trend="stable",
        )
        score = self.analyzer._compute_crowding_score(s)
        # High sector crowding pushes score up
        assert score >= 50

    def test_analyze_returns_signal(self):
        signal = self.analyzer.analyze()
        assert isinstance(signal, FundCrowdingSignal)
        assert 0 <= signal.crowding_score <= 100
        assert signal.risk_level in ("low", "medium", "high")
