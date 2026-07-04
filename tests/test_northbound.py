"""Tests for multi-dimensional northbound profile analysis."""

import pytest
import pandas as pd
from src.game_theory.northbound import (
    NorthboundAnalyzer,
    NorthboundProfile,
)


class TestNorthboundProfile:
    def test_default_construction(self):
        p = NorthboundProfile()
        assert p.total_net_flow == 0.0
        assert p.style_preference == "balanced"
        assert p.score == 50
        assert p.momentum_signal == "neutral"

    def test_full_profile(self):
        p = NorthboundProfile(
            total_net_flow=80.5,
            consecutive_days=5,
            flow_acceleration=0.8,
            style_preference="value",
            momentum_signal="accelerating",
            is_inflow_sustained=True,
        )
        assert p.is_inflow_sustained
        assert p.consecutive_days == 5


class TestNorthboundAnalyzer:
    def setup_method(self):
        self.analyzer = NorthboundAnalyzer()

    def test_count_consecutive_positive(self):
        series = pd.Series([10, -5, 20, 30, 40])
        result = self.analyzer._count_consecutive(series)
        assert result == 3  # Last 3 days positive

    def test_count_consecutive_negative(self):
        series = pd.Series([10, -5, -10, -15])
        result = self.analyzer._count_consecutive(series)
        assert result == -3

    def test_count_consecutive_empty(self):
        result = self.analyzer._count_consecutive(pd.Series([]))
        assert result == 0

    def test_compute_composite_score_strong_inflow(self):
        p = NorthboundProfile(
            total_net_flow=100.0,
            flow_acceleration=1.0,
            consecutive_days=5,
            style_preference="value",
        )
        score = self.analyzer._compute_composite_score(p)
        assert score >= 70  # Strong signal

    def test_compute_composite_score_outflow(self):
        p = NorthboundProfile(
            total_net_flow=-80.0,
            flow_acceleration=-1.5,
            consecutive_days=-5,
        )
        score = self.analyzer._compute_composite_score(p)
        assert score <= 30  # Weak signal

    def test_compute_composite_score_neutral(self):
        p = NorthboundProfile()
        score = self.analyzer._compute_composite_score(p)
        assert 40 <= score <= 60

    def test_cache_operations(self):
        self.analyzer._mem_set("key", "value")
        assert self.analyzer._mem_get("key") == "value"
        self.analyzer.cache_clear()
        assert self.analyzer._mem_get("key") is None
