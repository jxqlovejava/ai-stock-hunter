"""Tests for earnings revision factor analysis."""

import pytest
from src.data.earnings_revision import (
    EarningsRevisionAnalyzer,
    EarningsRevisionFactor,
)


class TestEarningsRevisionFactor:
    def test_default_construction(self):
        f = EarningsRevisionFactor(symbol="600519")
        assert f.revision_score == 50
        assert f.consensus_trend == "stable"
        assert f.earnings_momentum == "neutral"
        assert f.upgrade_count == 0
        assert f.upgrade_downgrade_ratio == 1.0

    def test_strong_upgrade(self):
        f = EarningsRevisionFactor(
            symbol="600519",
            upgrade_count=5,
            downgrade_count=1,
            upgrade_downgrade_ratio=5.0,
            consensus_trend="rising",
            earnings_momentum="accelerating",
        )
        assert f.upgrade_downgrade_ratio == 5.0
        assert f.consensus_trend == "rising"


class TestEarningsRevisionAnalyzer:
    def setup_method(self):
        self.analyzer = EarningsRevisionAnalyzer()

    def test_compute_revision_score_strong_upgrade(self):
        f = EarningsRevisionFactor(
            symbol="600519",
            upgrade_count=5,
            downgrade_count=0,
            upgrade_downgrade_ratio=5.0,
            consensus_trend="rising",
            earnings_momentum="accelerating",
        )
        score = self.analyzer._compute_revision_score(f)
        assert score >= 75

    def test_compute_revision_score_many_downgrades(self):
        f = EarningsRevisionFactor(
            symbol="000001",
            upgrade_count=0,
            downgrade_count=5,
            upgrade_downgrade_ratio=0.2,
            consensus_trend="falling",
            earnings_momentum="decelerating",
        )
        score = self.analyzer._compute_revision_score(f)
        assert score <= 30

    def test_compute_revision_score_neutral(self):
        f = EarningsRevisionFactor(symbol="000001")
        score = self.analyzer._compute_revision_score(f)
        assert 40 <= score <= 60

    def test_consensus_trend_rising(self):
        import pandas as pd
        # Simulate rising forecasts: 10, 11, 12, 13, 14
        df = pd.DataFrame({"eps_forecast": [10.0, 11.0, 12.0, 13.0, 14.0]})
        result = self.analyzer._compute_consensus_trend(df)
        assert result == "rising"

    def test_consensus_trend_stable(self):
        import pandas as pd
        df = pd.DataFrame({"eps_forecast": [10.0, 10.1, 9.9, 10.2, 10.0]})
        result = self.analyzer._compute_consensus_trend(df)
        assert result == "stable"

    def test_compute_dispersion(self):
        import pandas as pd
        df = pd.DataFrame({"eps_forecast": [10.0, 11.0, 12.0]})
        result = self.analyzer._compute_dispersion(df)
        assert result is not None
        assert result > 0  # Some dispersion exists

    def test_earnings_momentum_accelerating(self):
        f = EarningsRevisionFactor(
            symbol="600519",
            upgrade_downgrade_ratio=2.0,
            consensus_trend="rising",
            upgrade_count=5,
        )
        result = self.analyzer._compute_earnings_momentum(f)
        assert result == "accelerating"

    def test_cache_operations(self):
        f = EarningsRevisionFactor(symbol="test")
        self.analyzer._cache_set("test_key", f)
        assert self.analyzer._cache_get("test_key") is not None
        self.analyzer.cache_clear()
        assert self.analyzer._cache_get("test_key") is None
