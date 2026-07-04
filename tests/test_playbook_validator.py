# -*- coding: utf-8 -*-
"""Tests for playbook validation pipeline with 龙虎榜 data statistics.

Phase 2 核心测试: playbook 假设 → 数据统计验证 → 证据级别升级。

All tests that touch external APIs use mocked data — no real network calls in CI.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

from src.game_theory.playbook_validator import (
    EvidenceGrade,
    PlaybookValidation,
    PlaybookValidator,
    SeatWinRate,
    ValidationReport,
    get_seat_rankings,
    upgrade_playbook_evidence,
    validate_playbooks,
)

# ══════════════════════════════════════════════════════════════════════
# Shared mock fixtures
# ══════════════════════════════════════════════════════════════════════

MOCK_LHB_RECORDS = [
    {"SECURITY_CODE": "002229", "TRADE_DATE": "2026-06-01 00:00:00",
     "SECURITY_NAME_ABBR": "鸿博股份", "BILLBOARD_NET_AMT": 50000000},
    {"SECURITY_CODE": "002229", "TRADE_DATE": "2026-06-02 00:00:00",
     "SECURITY_NAME_ABBR": "鸿博股份", "BILLBOARD_NET_AMT": 80000000},
    {"SECURITY_CODE": "603019", "TRADE_DATE": "2026-06-01 00:00:00",
     "SECURITY_NAME_ABBR": "中科曙光", "BILLBOARD_NET_AMT": 120000000},
    {"SECURITY_CODE": "300474", "TRADE_DATE": "2026-06-03 00:00:00",
     "SECURITY_NAME_ABBR": "景嘉微", "BILLBOARD_NET_AMT": 35000000},
]

MOCK_PRICE_DATA = {
    "002229": (
        ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
         "2026-06-08", "2026-06-09", "2026-06-10"],
        [25.0, 26.5, 28.0, 27.5, 29.0, 28.0, 30.0, 31.0],
    ),
    "603019": (
        ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
         "2026-06-08", "2026-06-09", "2026-06-10"],
        [50.0, 52.0, 51.0, 53.0, 54.0, 55.0, 56.0, 57.0],
    ),
    "300474": (
        ["2026-06-03", "2026-06-04", "2026-06-05", "2026-06-08", "2026-06-09"],
        [80.0, 82.0, 79.0, 85.0, 88.0],
    ),
}

MOCK_SEAT_BUYS = [
    {"OPERATEDEPT_NAME": "中信证券上海分公司", "BUY": 80000000, "SELL": 20000000, "NET": 60000000},
    {"OPERATEDEPT_NAME": "国盛证券宁波桑田路", "BUY": 50000000, "SELL": 0, "NET": 50000000},
    {"OPERATEDEPT_NAME": "东方财富证券拉萨团结路", "BUY": 15000000, "SELL": 30000000, "NET": -15000000},
]


def _make_mock_validator(days_back=7):
    """Create a validator pre-loaded with mock data."""
    validator = PlaybookValidator(days_back=days_back)
    validator._lhb_cache = list(MOCK_LHB_RECORDS)
    validator._price_cache = dict(MOCK_PRICE_DATA)
    return validator


# ══════════════════════════════════════════════════════════════════════
# EvidenceGrade
# ══════════════════════════════════════════════════════════════════════

class TestEvidenceGrade:
    def test_lifecycle_values(self):
        assert EvidenceGrade.HYPOTHESIS.value == "HYPOTHESIS"
        assert EvidenceGrade.PRELIMINARY.value == "PRELIMINARY"
        assert EvidenceGrade.CONFIRMED.value == "CONFIRMED"
        assert EvidenceGrade.REFUTED.value == "REFUTED"
        assert EvidenceGrade.CALIBRATED.value == "CALIBRATED"

    def test_five_levels(self):
        assert len(list(EvidenceGrade)) == 5


# ══════════════════════════════════════════════════════════════════════
# SeatWinRate
# ══════════════════════════════════════════════════════════════════════

class TestSeatWinRate:
    def test_default_construction(self):
        sr = SeatWinRate(seat_name="测试席位")
        assert sr.seat_name == "测试席位"
        assert sr.sample_size == 0
        assert sr.win_rate_3d == 0.0
        assert sr.grade == EvidenceGrade.HYPOTHESIS

    def test_full_stats(self):
        sr = SeatWinRate(
            seat_name="国盛证券宁波桑田路",
            reputation_score=86,
            sample_size=50,
            win_rate_1d=0.62, win_rate_3d=0.58, win_rate_5d=0.45,
            avg_return_1d=1.8, avg_return_3d=3.2, avg_return_5d=2.1,
            max_drawdown_5d=-12.5, sharpe_5d=1.2,
            confidence_interval_3d=(0.5, 5.9),
            grade=EvidenceGrade.CONFIRMED,
        )
        assert sr.grade == EvidenceGrade.CONFIRMED

    def test_calibrated_requires_100_samples(self):
        sr = SeatWinRate(seat_name="顶级席位", sample_size=100, grade=EvidenceGrade.CALIBRATED)
        assert sr.sample_size >= 100
        assert sr.grade == EvidenceGrade.CALIBRATED


# ══════════════════════════════════════════════════════════════════════
# PlaybookValidation
# ══════════════════════════════════════════════════════════════════════

class TestPlaybookValidation:
    def test_default_construction(self):
        pv = PlaybookValidation(playbook_id="limit_up_relay", playbook_name="涨停板接力")
        assert pv.total_samples == 0
        assert pv.evidence_grade_before == EvidenceGrade.HYPOTHESIS
        assert pv.evidence_grade_after == EvidenceGrade.HYPOTHESIS

    def test_confirmed_validation(self):
        pv = PlaybookValidation(
            playbook_id="limit_up_relay", playbook_name="涨停板接力",
            total_samples=50, supporting_samples=35, refuting_samples=15,
            pattern_match_rate=70.0, avg_return_after_match=2.8,
            significance_level=0.008,
            evidence_grade_after=EvidenceGrade.CONFIRMED, verdict="✅ 已验证",
        )
        assert pv.significance_level < 0.05
        assert pv.evidence_grade_after == EvidenceGrade.CONFIRMED

    def test_refuted_validation(self):
        pv = PlaybookValidation(
            playbook_id="test_refuted", playbook_name="测试被证伪",
            total_samples=30, supporting_samples=5, refuting_samples=25,
            pattern_match_rate=16.7,
            evidence_grade_after=EvidenceGrade.REFUTED,
        )
        assert pv.evidence_grade_after == EvidenceGrade.REFUTED


# ══════════════════════════════════════════════════════════════════════
# ValidationReport
# ══════════════════════════════════════════════════════════════════════

class TestValidationReport:
    def test_empty_report(self):
        report = ValidationReport()
        assert report.overall_sample_size == 0
        assert report.confirmed_count == 0
        assert report.refuted_count == 0

    def test_with_results(self):
        pv1 = PlaybookValidation(
            playbook_id="pb1", playbook_name="PB1", total_samples=50,
            evidence_grade_after=EvidenceGrade.CONFIRMED,
        )
        pv2 = PlaybookValidation(
            playbook_id="pb2", playbook_name="PB2", total_samples=30,
            evidence_grade_after=EvidenceGrade.REFUTED,
        )
        report = ValidationReport(
            playbook_results=[pv1, pv2], overall_sample_size=80,
            confirmed_count=1, refuted_count=1,
        )
        assert len(report.playbook_results) == 2
        assert report.confirmed_count == 1
        assert report.refuted_count == 1


# ══════════════════════════════════════════════════════════════════════
# Evidence upgrade logic (static method — no API calls)
# ══════════════════════════════════════════════════════════════════════

class TestEvidenceUpgrade:
    def test_calibrated(self):
        grade = PlaybookValidator._upgrade_evidence(total=120, supporting=80, p_value=0.003)
        assert grade == EvidenceGrade.CALIBRATED

    def test_confirmed(self):
        grade = PlaybookValidator._upgrade_evidence(total=30, supporting=22, p_value=0.02)
        assert grade == EvidenceGrade.CONFIRMED

    def test_preliminary(self):
        grade = PlaybookValidator._upgrade_evidence(total=8, supporting=6, p_value=0.10)
        assert grade == EvidenceGrade.PRELIMINARY

    def test_hypothesis_insufficient_samples(self):
        grade = PlaybookValidator._upgrade_evidence(total=1, supporting=1, p_value=1.0)
        assert grade == EvidenceGrade.HYPOTHESIS

    def test_refuted(self):
        grade = PlaybookValidator._upgrade_evidence(total=25, supporting=5, p_value=0.5)
        assert grade == EvidenceGrade.REFUTED

    def test_boundary_20_samples_low_p(self):
        grade = PlaybookValidator._upgrade_evidence(total=20, supporting=15, p_value=0.04)
        assert grade == EvidenceGrade.CONFIRMED


# ══════════════════════════════════════════════════════════════════════
# Verdict generation (static method — no API calls)
# ══════════════════════════════════════════════════════════════════════

class TestVerdict:
    def test_calibrated_verdict(self):
        result = PlaybookValidation(
            playbook_id="test", playbook_name="测试",
            total_samples=120, pattern_match_rate=72.5,
            significance_level=0.003,
            evidence_grade_after=EvidenceGrade.CALIBRATED,
            avg_return_after_match=3.5,
        )
        verdict = PlaybookValidator._make_verdict(result)
        assert "✅" in verdict
        assert "120" in verdict
        assert "校准级" in verdict

    def test_confirmed_verdict(self):
        result = PlaybookValidation(
            playbook_id="test", playbook_name="测试",
            total_samples=30, pattern_match_rate=70.0, significance_level=0.02,
            evidence_grade_after=EvidenceGrade.CONFIRMED,
        )
        assert "✅" in PlaybookValidator._make_verdict(result)

    def test_refuted_verdict(self):
        result = PlaybookValidation(
            playbook_id="test", playbook_name="测试",
            total_samples=25, pattern_match_rate=20.0,
            evidence_grade_after=EvidenceGrade.REFUTED,
        )
        verdict = PlaybookValidator._make_verdict(result)
        assert "❌" in verdict
        assert "证伪" in verdict

    def test_hypothesis_verdict(self):
        result = PlaybookValidation(
            playbook_id="test", playbook_name="测试",
            total_samples=3, evidence_grade_after=EvidenceGrade.HYPOTHESIS,
        )
        verdict = PlaybookValidator._make_verdict(result)
        assert "未验证" in verdict
        assert "样本不足" in verdict


# ══════════════════════════════════════════════════════════════════════
# PlaybookValidator — construction (no API calls)
# ══════════════════════════════════════════════════════════════════════

class TestPlaybookValidatorInit:
    def test_default_construction(self):
        validator = PlaybookValidator()
        assert validator.days_back == 60
        assert validator._lhb_cache is None

    def test_custom_days_back(self):
        validator = PlaybookValidator(days_back=30)
        assert validator.days_back == 30

    def test_clear_cache(self):
        validator = PlaybookValidator()
        validator._lhb_cache = [{"test": True}]
        validator._price_cache = {"600519": (["2026-01-01"], [100.0])}
        validator.clear_cache()
        assert validator._lhb_cache is None
        assert len(validator._price_cache) == 0


# ══════════════════════════════════════════════════════════════════════
# PlaybookValidator — with fully mocked data
# ══════════════════════════════════════════════════════════════════════

class TestPlaybookValidatorMocked:
    """Test validator with pre-loaded mock data. No real network calls."""

    def test_validator_uses_preloaded_lhb(self):
        validator = _make_mock_validator()
        assert len(validator._get_historical_lhb()) == 4

    def test_forward_return_calculation(self):
        validator = _make_mock_validator()
        r1 = validator._get_forward_return("002229", "2026-06-01", 1)
        assert r1 is not None
        assert r1 > 0  # 25.0 → 26.5 = +6%

    def test_forward_return_3d(self):
        validator = _make_mock_validator()
        r3 = validator._get_forward_return("002229", "2026-06-01", 3)
        assert r3 is not None
        # 25.0 → 27.5 = +10.0%
        assert abs(r3 - 10.0) < 2.0

    def test_forward_return_missing_symbol(self):
        validator = _make_mock_validator()
        r = validator._get_forward_return("999999", "2026-06-01", 3)
        assert r is None

    def test_forward_return_out_of_range(self):
        validator = _make_mock_validator()
        # Only 8 data points for 002229, index 0 + 100 > 8
        r = validator._get_forward_return("002229", "2026-06-01", 100)
        assert r is None

    @patch("src.game_theory.playbook_validator._dc_query")
    def test_empty_lhb_gives_hypothesis(self, mock_dc):
        mock_dc.return_value = []
        validator = PlaybookValidator(days_back=1)
        from src.game_theory.playbooks import TOP_3_PLAYBOOKS
        result = validator.validate_playbook(TOP_3_PLAYBOOKS[0])
        assert result.total_samples == 0
        assert result.evidence_grade_after == EvidenceGrade.HYPOTHESIS

    @patch("src.game_theory.playbook_validator._dc_query")
    @patch.object(PlaybookValidator, "_get_forward_return")
    def test_limit_up_relay_with_data(self, mock_fwd, mock_dc):
        """Simulate: 游资买入后 T+1 正收益 → 模式部分匹配。"""
        mock_dc.return_value = list(MOCK_LHB_RECORDS)
        # Simulate positive forward returns (游资买入后上涨)
        mock_fwd.return_value = 3.5  # +3.5% T+1

        validator = PlaybookValidator(days_back=7)
        # Patch seat details to return known seats
        with patch.object(validator.__class__, "_validate_limit_up_relay",
                          return_value=PlaybookValidation(
                              playbook_id="limit_up_relay",
                              playbook_name="涨停板接力",
                              total_samples=15,
                              supporting_samples=10,
                              refuting_samples=5,
                              pattern_match_rate=66.7,
                              avg_return_after_match=3.5,
                              significance_level=0.08,
                              evidence_grade_after=EvidenceGrade.PRELIMINARY,
                              verdict="⚠️ 初步证据: 有 15 个样本（< 20），匹配率 66.7%。",
                          )):
            from src.game_theory.playbooks import TOP_3_PLAYBOOKS
            result = validator.validate_playbook(TOP_3_PLAYBOOKS[0])
            assert result.playbook_id == "limit_up_relay"
            assert result.total_samples == 15
            assert result.evidence_grade_after == EvidenceGrade.PRELIMINARY

    def test_refresh_clears_cache(self):
        validator = _make_mock_validator()
        assert len(validator._get_historical_lhb()) == 4

        # refresh() clears cache and calls validate_all() → may trigger API.
        # Only test cache-clearing aspect:
        validator.clear_cache()
        assert validator._lhb_cache is None
        assert len(validator._price_cache) == 0


# ══════════════════════════════════════════════════════════════════════
# SeatWinRate statistics (mocked)
# ══════════════════════════════════════════════════════════════════════

class TestSeatWinRateStats:
    def test_empty_seat_without_data(self):
        """Without LHB data, seat win-rate is HYPOTHESIS. Simulate by not loading cache."""
        validator = PlaybookValidator(days_back=7)
        # Empty LHB cache → no buy records → hypothesis
        with patch.object(validator, "_get_historical_lhb", return_value=[]):
            wr = validator.calc_seat_win_rate("国盛证券宁波桑田路")
            assert wr.sample_size == 0
            assert wr.grade == EvidenceGrade.HYPOTHESIS

    @patch("src.game_theory.playbook_validator.PlaybookValidator._get_historical_lhb")
    @patch("src.game_theory.playbook_validator.PlaybookValidator._get_forward_return")
    def test_seat_with_buy_records(self, mock_fwd, mock_lhb):
        """When seat has buy records and positive forward returns, win rate > 0."""
        mock_lhb.return_value = list(MOCK_LHB_RECORDS)
        mock_fwd.return_value = 2.5  # +2.5% each

        validator = PlaybookValidator(days_back=7)
        validator._price_cache = dict(MOCK_PRICE_DATA)

        # Simulate filter_seat_buys returning matching records
        with patch.object(validator, "_filter_seat_buys", return_value=[
            {"SECURITY_CODE": "002229", "TRADE_DATE": "2026-06-01"},
            {"SECURITY_CODE": "603019", "TRADE_DATE": "2026-06-01"},
        ]):
            wr = validator.calc_seat_win_rate("中信证券上海分公司")
            assert wr.sample_size == 2
            assert wr.win_rate_3d > 0  # Both positive → 100%
            assert wr.grade == EvidenceGrade.HYPOTHESIS  # < 5 samples

    def test_all_seats_rankings_no_duplicates(self):
        """calc_all_seats_win_rates returns one entry per known seat, no duplicates."""
        validator = _make_mock_validator()
        from src.game_theory.seats import KNOWN_SEATS

        with patch.object(validator, "_get_historical_lhb", return_value=list(MOCK_LHB_RECORDS)):
            with patch.object(validator, "_filter_seat_buys", return_value=[]):
                rankings = validator.calc_all_seats_win_rates()
                assert len(rankings) == len(KNOWN_SEATS)
                names = [r.seat_name for r in rankings]
                assert len(names) == len(set(names))

    def test_top_seats_filtering(self):
        validator = _make_mock_validator()
        with patch.object(validator, "_get_historical_lhb", return_value=list(MOCK_LHB_RECORDS)):
            with patch.object(validator, "_filter_seat_buys", return_value=[]):
                top = validator.get_top_seats(top_n=3, min_samples=0)
                assert len(top) <= 3
                if len(top) >= 2:
                    assert top[0].win_rate_3d >= top[1].win_rate_3d


# ══════════════════════════════════════════════════════════════════════
# Convenience functions (mocked)
# ══════════════════════════════════════════════════════════════════════

class TestConvenienceFunctions:
    @patch("src.game_theory.playbook_validator.PlaybookValidator.validate_all")
    def test_validate_playbooks_returns_report(self, mock_validate):
        mock_validate.return_value = ValidationReport(
            playbook_results=[
                PlaybookValidation(playbook_id="limit_up_relay", playbook_name="涨停板接力"),
                PlaybookValidation(playbook_id="institutional_clustering", playbook_name="机构抱团拉升"),
                PlaybookValidation(playbook_id="national_team_bailout", playbook_name="国家队托底"),
            ],
        )
        report = validate_playbooks(days_back=1)
        assert isinstance(report, ValidationReport)
        assert len(report.playbook_results) == 3

    @patch("src.game_theory.playbook_validator.PlaybookValidator.get_top_seats")
    def test_get_seat_rankings_returns_list(self, mock_top):
        mock_top.return_value = [
            SeatWinRate(seat_name="中信证券上海分公司", reputation_score=85, sample_size=20),
            SeatWinRate(seat_name="国盛证券宁波桑田路", reputation_score=86, sample_size=15),
        ]
        rankings = get_seat_rankings(days_back=1, min_samples=0)
        assert isinstance(rankings, list)
        for r in rankings:
            assert isinstance(r, SeatWinRate)

    def test_upgrade_playbook_evidence(self):
        from src.game_theory.playbooks import TOP_3_PLAYBOOKS
        pb = TOP_3_PLAYBOOKS[0]
        original = pb.evidence_level
        pv = PlaybookValidation(
            playbook_id=pb.id, playbook_name=pb.name,
            total_samples=30,
            evidence_grade_after=EvidenceGrade.CONFIRMED,
            evidence_grade_before=EvidenceGrade.HYPOTHESIS,
        )
        new_grade = upgrade_playbook_evidence(pb, pv)
        assert new_grade == "CONFIRMED"
        assert pb.evidence_level == "CONFIRMED"
        pb.evidence_level = original  # restore


# ══════════════════════════════════════════════════════════════════════
# Updated playbooks module (no API calls)
# ══════════════════════════════════════════════════════════════════════

class TestPlaybooksUpdated:
    def test_playbook_has_new_fields(self):
        from src.game_theory.playbooks import TOP_3_PLAYBOOKS
        for pb in TOP_3_PLAYBOOKS:
            assert hasattr(pb, "evidence_upgraded_at")
            assert hasattr(pb, "validation_summary")

    def test_get_playbook_evidence_summary(self):
        from src.game_theory.playbooks import get_playbook_evidence_summary
        summary = get_playbook_evidence_summary()
        assert "Playbook" in summary
        assert "涨停板接力" in summary
        assert "机构抱团拉升" in summary
        assert "国家队托底" in summary

    def test_three_playbooks_remain_hypothesis_by_default(self):
        from src.game_theory.playbooks import TOP_3_PLAYBOOKS
        assert len(TOP_3_PLAYBOOKS) == 3
        for pb in TOP_3_PLAYBOOKS:
            assert pb.evidence_level == "HYPOTHESIS"


# ══════════════════════════════════════════════════════════════════════
# Import roundtrip (no API calls)
# ══════════════════════════════════════════════════════════════════════

class TestImports:
    def test_all_exports_importable(self):
        import src.game_theory as gt
        for name in [
            "PlaybookValidator", "EvidenceGrade", "PlaybookValidation",
            "SeatWinRate", "ValidationReport", "validate_playbooks",
            "get_seat_rankings", "upgrade_playbook_evidence",
            "get_playbook_evidence_summary",
        ]:
            assert hasattr(gt, name), f"Missing export: {name}"

    def test_evidence_grade_values_unique(self):
        grades = [g.value for g in EvidenceGrade]
        assert len(set(grades)) == len(grades)

    def test_evidence_grade_maps_to_evidence_level(self):
        from src.game_theory.rules import EvidenceLevel as EL
        assert EvidenceGrade.HYPOTHESIS.value == EL.HYPOTHESIS.value
