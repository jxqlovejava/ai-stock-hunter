"""Tests for dragon & tiger seat recognition."""

import pytest
from src.game_theory.seats import (
    KNOWN_SEATS,
    SeatInfo,
    SeatActivity,
    SeatTracker,
)


class TestSeatInfo:
    def test_known_seats_non_empty(self):
        assert len(KNOWN_SEATS) >= 20  # At least 20 known seats

    def test_known_seats_have_scores(self):
        for seat in KNOWN_SEATS:
            assert 0 <= seat.reputation_score <= 100
            assert seat.seat_name
            assert seat.holding_period in ("日内", "隔日", "短线", "中线")

    def test_top_seats_identified(self):
        top_names = {s.seat_name for s in KNOWN_SEATS if s.reputation_score >= 80}
        assert len(top_names) >= 5  # Several high-reputation seats


class TestSeatActivity:
    def test_default_construction(self):
        a = SeatActivity(seat_name="测试席位", stock_symbol="600519")
        assert not a.identified
        assert a.following_signal == "neutral"
        assert a.buy_amount == 0.0

    def test_with_seat_info(self):
        info = SeatInfo(
            seat_name="中信证券上海分公司",
            reputation_score=85,
            typical_sectors=["科技", "半导体"],
            avg_position_size=5000,
        )
        a = SeatActivity(
            seat_name="中信证券上海分公司",
            stock_symbol="688256",
            stock_name="寒武纪",
            buy_amount=5000,
            seat_info=info,
            identified=True,
            following_signal="strong_buy",
        )
        assert a.identified
        assert a.following_signal == "strong_buy"


class TestSeatTracker:
    def setup_method(self):
        self.tracker = SeatTracker()

    def test_build_index(self):
        # Index should contain all known seats + aliases
        assert len(self.tracker._seats) > 0

    def test_classify_seat_exact_match(self):
        activity = self.tracker._classify_seat("中信证券上海分公司")
        assert activity.identified
        assert activity.seat_info is not None
        assert activity.following_signal == "strong_buy"  # rep 85 >= 85

    def test_classify_seat_unknown(self):
        activity = self.tracker._classify_seat("某个不知名营业部")
        assert not activity.identified
        assert activity.following_signal == "neutral"

    def test_classify_seat_partial_match(self):
        # "华泰益田路" is an alias for "华泰证券深圳益田路"
        activity = self.tracker._classify_seat("华泰益田路")
        assert activity.identified

    def test_list_known_seats(self):
        seats = self.tracker.list_known_seats()
        assert len(seats) == len(KNOWN_SEATS)

    def test_safe_float(self):
        assert SeatTracker._safe_float("100.5") == 100.5
        assert SeatTracker._safe_float("invalid") == 0.0
        assert SeatTracker._safe_float(None) == 0.0
