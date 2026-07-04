"""Tests for market dominant player classifier."""

import pytest
from src.game_theory.dominance import DominanceClassifier, DominanceProfile


class TestDominanceProfile:
    def test_default_construction(self):
        p = DominanceProfile()
        assert p.dominant_player is None
        assert p.confidence == 0.0
        assert p.market_regime == "mixed"
        assert p.volatility_regime == "medium"

    def test_hot_money_regime(self):
        p = DominanceProfile(
            dominant_player="HOT_MONEY",
            confidence=0.8,
            market_regime="hot_money_market",
            recommended_strategy="跟随游资",
        )
        assert p.dominant_player == "HOT_MONEY"


class TestDominanceClassifier:
    def setup_method(self):
        self.clf = DominanceClassifier()

    def test_to_market_regime_mapping(self):
        assert self.clf._to_market_regime("HOT_MONEY") == "hot_money_market"
        assert self.clf._to_market_regime("INSTITUTIONAL") == "institutional_market"
        assert self.clf._to_market_regime("QUANT") == "quant_market"
        assert self.clf._to_market_regime("NATIONAL_TEAM") == "national_team_active"
        assert self.clf._to_market_regime("NORTHBOUND") == "northbound_driven"
        assert self.clf._to_market_regime(None) == "mixed"

    def test_recommend_strategy_all_players(self):
        for player in ["HOT_MONEY", "INSTITUTIONAL", "QUANT", "NATIONAL_TEAM", "NORTHBOUND"]:
            p = DominanceProfile(dominant_player=player)
            strategy = self.clf._recommend_strategy(p)
            assert len(strategy) > 10  # Non-trivial recommendation

    def test_recommend_strategy_unknown(self):
        p = DominanceProfile(dominant_player=None)
        strategy = self.clf._recommend_strategy(p)
        assert len(strategy) > 0

    def test_cache_operations(self):
        self.clf._cache_set("key", {"test": 123})
        assert self.clf._cache_get("key") == {"test": 123}
        self.clf.cache_clear()
        assert self.clf._cache_get("key") is None
