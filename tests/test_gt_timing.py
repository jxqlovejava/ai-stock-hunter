# -*- coding: utf-8 -*-
"""技术 × 博弈论 买/卖点融合测试。"""

from __future__ import annotations

from types import SimpleNamespace

from src.routing.gt_timing import fuse_timing_with_game_theory


def _entry(etype="PULLBACK_SUPPORT", conf=0.6):
    return SimpleNamespace(
        type=etype,
        description="test entry",
        entry_zone_low=50.0,
        entry_zone_high=51.0,
        confidence=conf,
    )


def _exit(etype="MA_BREAKDOWN", conf=0.55, urgency="NORMAL"):
    return SimpleNamespace(
        type=etype,
        description="test exit",
        exit_zone_low=48.0,
        exit_zone_high=49.0,
        confidence=conf,
        urgency=urgency,
    )


def test_wait_when_no_signals():
    adv = fuse_timing_with_game_theory(None, None, held=False)
    assert adv.action == "WAIT"
    assert adv.entry_allowed is False


def test_enter_on_institutional_pullback():
    timing = SimpleNamespace(
        best_entry=_entry("PULLBACK_SUPPORT", 0.6),
        exit_signals=[],
    )
    gt = {
        "score": 62,
        "dominant_player": "institutional",
        "seat_signal": "bullish",
        "crowding_score": 40,
        "northbound_score": 60,
        "margin_score": 50,
        "risks": [],
    }
    adv = fuse_timing_with_game_theory(timing, gt, held=False, current_price=50.5)
    assert adv.action == "ENTER"
    assert adv.entry_allowed is True
    assert "PULLBACK" in adv.buy_point or "PULLBACK_SUPPORT" in adv.buy_point


def test_block_entry_when_crowded():
    timing = SimpleNamespace(
        best_entry=_entry("BREAKOUT", 0.8),
        exit_signals=[],
    )
    gt = {
        "score": 55,
        "dominant_player": "institutional",
        "seat_signal": "bullish",
        "crowding_score": 75,
        "northbound_score": 50,
        "margin_score": 50,
        "risks": ["sector_crowded"],
    }
    adv = fuse_timing_with_game_theory(timing, gt, held=False)
    assert adv.entry_allowed is False
    assert adv.action == "WAIT"
    assert adv.size_hint <= 0.3


def test_exit_on_hot_money_stall_held():
    timing = SimpleNamespace(
        best_entry=None,
        exit_signals=[_exit("VOLUME_STALL", 0.6)],
    )
    gt = {
        "score": 40,
        "dominant_player": "hot_money",
        "seat_signal": "bearish",
        "crowding_score": 65,
        "northbound_score": 40,
        "margin_score": 80,
        "risks": [],
    }
    adv = fuse_timing_with_game_theory(
        timing, gt, held=True, position_loss_pct=-0.05
    )
    assert adv.action in ("EXIT", "REDUCE")
    assert adv.exit_urgency in ("normal", "high", "urgent")
    assert "卖" in adv.sell_point or adv.tech_exit_type == "VOLUME_STALL" or "席位" in adv.sell_point


def test_catching_knife_blocks_entry():
    timing = SimpleNamespace(
        best_entry=_entry("OVERSOLD_BOUNCE", 0.7),
        exit_signals=[],
    )
    gt = {
        "score": 50,
        "dominant_player": "retail",
        "seat_signal": "neutral",
        "crowding_score": 40,
        "northbound_score": 50,
        "margin_score": 50,
        "risks": [],
    }
    adv = fuse_timing_with_game_theory(
        timing, gt, held=False, bottom_phase="CATCHING_KNIFE"
    )
    assert adv.entry_allowed is False
    assert adv.action == "WAIT"
