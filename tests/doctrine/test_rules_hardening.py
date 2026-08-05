# -*- coding: utf-8 -*-
"""P0-2 / P0-4 军规补齐测试。

覆盖:
  - r042 亏损后禁止报复性加仓 (BLOCK)
  - r043 信息面冲突即禁止开仓 (BLOCK)
  - r017 连续止损休整 激活 (BLOCK)
  - 规则编号唯一性（大小写不冲突）
  - P0-4 补全的至少 2 条规则可触发
"""

from __future__ import annotations

from src.doctrine.checker import DoctrineChecker
from src.doctrine.rules import MILITARY_RULES

_checker = DoctrineChecker()


def _blocked(ctx: dict) -> list[str]:
    return [r.id for r in _checker.check("600519", ctx).blocked_by]


# ── r042 亏损后禁止报复性加仓 ──

def test_r042_blocked_on_add_after_stop():
    ctx = {"recent_stops": [{"date": "2026-08-05"}], "intended_action": "ADD"}
    assert "r042" in _blocked(ctx)


def test_r042_blocked_on_buy_signal_with_stop_count():
    ctx = {"recent_stops": 1, "signal_action": "BUY"}
    assert "r042" in _blocked(ctx)


def test_r042_not_triggered_without_stop():
    assert "r042" not in _blocked({"recent_stops": [], "intended_action": "ADD"})


def test_r042_not_triggered_without_add_intent():
    ctx = {"recent_stops": [{"date": "2026-08-05"}], "intended_action": "HOLD"}
    assert "r042" not in _blocked(ctx)


def test_r042_not_triggered_without_data():
    # 无 recent_stops / stop_occurred_today → 防御性不误报
    assert "r042" not in _blocked({"intended_action": "ADD"})


# ── r043 信息面冲突即禁止开仓 ──

def test_r043_blocked_on_fundamental_negative():
    ctx = {"signal_action": "BUY", "fundamental_direction": "NEGATIVE"}
    assert "r043" in _blocked(ctx)


def test_r043_blocked_on_news_negative():
    ctx = {"technical_direction": "BUY", "news_polarity": -0.5}
    assert "r043" in _blocked(ctx)


def test_r043_blocked_on_info_conflict_flag():
    ctx = {"signal_action": "BUY", "info_conflict": True}
    assert "r043" in _blocked(ctx)


def test_r043_not_triggered_on_buy_alone():
    # 只有买入信号、无负面信息 → 不误报
    assert "r043" not in _blocked({"signal_action": "BUY"})


def test_r043_not_triggered_on_sell_signal():
    ctx = {"signal_action": "SELL", "fundamental_direction": "NEGATIVE"}
    assert "r043" not in _blocked(ctx)


# ── r017 连续止损休整 激活 ──

def test_r017_blocked_at_three_consecutive_stops():
    assert "r017" in _blocked({"consecutive_stops": 3})


def test_r017_not_blocked_below_three():
    assert "r017" not in _blocked({"consecutive_stops": 2})


def test_r017_not_triggered_when_missing():
    # 字段缺失 / None → 无数据不触发
    assert "r017" not in _blocked({})
    assert "r017" not in _blocked({"consecutive_stops": None})


# ── P0-4 编号唯一性 ──

def test_rule_ids_unique_case_insensitive():
    ids = [r.id for r in MILITARY_RULES]
    lower = [i.lower() for i in ids]
    assert len(set(lower)) == len(ids), "规则 ID 存在大小写冲突"


def test_renumbered_antimanipulation_ids_present():
    ids = {r.id for r in MILITARY_RULES}
    assert "r039" in ids and "r040" in ids and "r041" in ids
    # 旧的大写冲突编号必须移除
    assert "R032" not in ids and "R033" not in ids and "R034" not in ids


# ── P0-4 补全规则可触发 ──

def test_r001_filled_position_cap():
    assert "r001" in _blocked({"single_stock_pct": 30.0, "max_single_pct": 20.0})


def test_r002_filled_total_exposure():
    assert "r002" in _blocked({"total_stock_pct": 90.0})


def test_r022_filled_source_cross_validation():
    assert "r022" in _blocked({"source_tier1_count": 1})


def test_r039_filled_chip_concentration():
    warns = [r.id for r in _checker.check("600519", {"top10_holding_pct": 65.0}).warnings]
    assert "r039" in warns


def test_r040_filled_manipulation_history():
    warns = [r.id for r in _checker.check("600519", {"manipulation_history_count": 3}).warnings]
    assert "r040" in warns


def test_r028_filled_trailing_stop():
    warns = [r.id for r in _checker.check("600519", {"unrealized_profit_pct": 35.0}).warnings]
    assert "r028" in warns


def test_clean_stock_still_passes():
    result = _checker.check("600519", {"stock_name": "贵州茅台"})
    assert result.passed
    assert result.blocked_by == []
