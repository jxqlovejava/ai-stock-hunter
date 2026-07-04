"""Tests for monetary-credit quadrant framework."""

import pytest
from src.macro.monetary_credit import (
    MonetaryCreditAnalyzer,
    MacroRegime,
    Quadrant,
    QUADRANT_SECTOR_MAP,
)


class TestQuadrant:
    def test_quadrant_values(self):
        assert Quadrant.EASY_MONEY_EASY_CREDIT.value == "宽货币+宽信用"
        assert Quadrant.TIGHT_MONEY_TIGHT_CREDIT.value == "紧货币+紧信用"

    def test_quadrant_sector_map_coverage(self):
        for quadrant in Quadrant:
            assert quadrant in QUADRANT_SECTOR_MAP
            recommended, avoid = QUADRANT_SECTOR_MAP[quadrant]
            assert len(recommended) > 0


class TestMacroRegime:
    def test_default_construction(self):
        regime = MacroRegime(
            quadrant=Quadrant.EASY_MONEY_EASY_CREDIT,
            confidence=0.8,
        )
        assert regime.social_financing_growth is None
        assert regime.m1_m2_gap is None
        assert regime.confidence == 0.8

    def test_full_construction(self):
        regime = MacroRegime(
            quadrant=Quadrant.TIGHT_MONEY_TIGHT_CREDIT,
            confidence=0.9,
            social_financing_growth=4.5,
            m1_m2_gap=-3.5,
            lpr_1y=3.45,
            lpr_5y=4.20,
            dr007=2.10,
            transition_signals=["DR007高于政策利率"],
            recommended_sectors=["防御性消费", "公用事业"],
            avoid_sectors=["券商", "地产"],
        )
        assert regime.m1_m2_gap == -3.5
        assert len(regime.transition_signals) == 1


class TestMonetaryCreditAnalyzer:
    def setup_method(self):
        self.analyzer = MonetaryCreditAnalyzer()

    def test_classify_money_easy(self):
        # M1>M2 (positive gap) + DR007 below policy rate
        result = self.analyzer._classify_money(m1_m2_gap=2.0, dr007=1.40)
        assert result == "easy"

    def test_classify_money_tight(self):
        # Deep negative gap + DR007 above policy
        result = self.analyzer._classify_money(m1_m2_gap=-5.0, dr007=1.80)
        assert result == "tight"

    def test_classify_money_neutral_missing_data(self):
        result = self.analyzer._classify_money(m1_m2_gap=None, dr007=None)
        assert result == "neutral"

    def test_classify_credit_easy(self):
        # SF growth above nominal GDP
        result = self.analyzer._classify_credit(sf_growth=8.0, credit_pulse=3.0)
        assert result == "easy"

    def test_classify_credit_tight(self):
        result = self.analyzer._classify_credit(sf_growth=3.0, credit_pulse=-2.0)
        assert result == "tight"

    def test_classify_credit_neutral_missing(self):
        result = self.analyzer._classify_credit(sf_growth=None, credit_pulse=None)
        assert result == "neutral"

    def test_to_quadrant_all_combos(self):
        assert self.analyzer._to_quadrant("easy", "easy") == Quadrant.EASY_MONEY_EASY_CREDIT
        assert self.analyzer._to_quadrant("easy", "tight") == Quadrant.EASY_MONEY_TIGHT_CREDIT
        assert self.analyzer._to_quadrant("tight", "easy") == Quadrant.TIGHT_MONEY_EASY_CREDIT
        assert self.analyzer._to_quadrant("tight", "tight") == Quadrant.TIGHT_MONEY_TIGHT_CREDIT
        # Neutral money + easy credit → TIGHT_MONEY_EASY_CREDIT (tight/neutral grouped)
        assert self.analyzer._to_quadrant("neutral", "easy") == Quadrant.TIGHT_MONEY_EASY_CREDIT

    def test_extract_first_number_percentage(self):
        assert MonetaryCreditAnalyzer._extract_first_number("同比增长 8.5%") == 8.5
        assert MonetaryCreditAnalyzer._extract_first_number("为 3.45") == 3.45

    def test_extract_first_number_none(self):
        assert MonetaryCreditAnalyzer._extract_first_number("暂无数据") is None

    def test_cache_set_get(self):
        self.analyzer._cache_set("test_key", 42.0)
        assert self.analyzer._cache_get("test_key") == 42.0

    def test_cache_miss(self):
        assert self.analyzer._cache_get("nonexistent") is None
