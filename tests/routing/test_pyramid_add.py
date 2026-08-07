# -*- coding: utf-8 -*-
"""P2: 浮盈阶梯加仓 (海龟金字塔启发) — _resolve_final_action 单元测试。

全部为快照级纯函数测试，不触发网络。覆盖:
  ① 浮盈 ≥ 2×ATR + 信号干净 → HOLD 升级为 ADD
  ② 浮盈不足 → 不触发
  ③ URGENT 离场 / 周线 BEAR / KDJ AVOID_ENTRY 阻断
  ④ chase_blocked 对金字塔豁免 (加已有盈利仓 ≠ 追新仓)
  ⑤ 卖点优先 / 非持仓 语义不变
"""
from types import SimpleNamespace

from src.routing.tactics import (
    TacticalSnapshot,
    TacticsResult,
    _resolve_final_action,
)

SYMBOL = "000001"


def _result(rec="HOLD"):
    r = TacticsResult(symbol=SYMBOL, name="测试")
    r.verdict_recommendation = rec
    return r


def _snap(*, held=True, atr=1.0, entry=10.0, px=13.0, weekly="BULL",
          exit_signals=None, macd_kdj=None, chase_blocked=False,
          projected_target=0.0):
    snap = TacticalSnapshot(symbol=SYMBOL, name="测试")
    snap.held = held
    snap.atr = atr
    snap.position_entry = entry
    snap.current_price = px
    snap.weekly_direction = weekly
    snap.exit_signals = exit_signals or []
    snap.macd_kdj = macd_kdj
    snap.chase_blocked = chase_blocked
    snap.projected_target = projected_target
    return snap


def _advice(action=None, entry_allowed=True):
    return SimpleNamespace(action=action, entry_allowed=entry_allowed)


# ═══════════════════════════════════════════════════════════════════
# ① 触发条件
# ═══════════════════════════════════════════════════════════════════
def test_pyramid_add_upgrades_hold_to_add():
    r = _result("HOLD")
    snap = _snap(held=True, atr=1.0, entry=10.0, px=13.0)  # 浮盈 3×ATR
    _resolve_final_action(r, snap, None, True)
    assert r.action == "ADD"
    assert any("浮盈阶梯加仓" in w for w in r.warnings)


def test_pyramid_upgrades_buy_hold_to_add():
    """rec=BUY 且已持仓 → 基础 HOLD，金字塔升级为 ADD。"""
    r = _result("BUY")
    snap = _snap(held=True, atr=1.0, entry=10.0, px=13.0)
    _resolve_final_action(r, snap, None, True)
    assert r.action == "ADD"


def test_pyramid_allows_normal_exit_signal():
    """非 URGENT 出场信号 (超买回落) 不阻断金字塔。"""
    r = _result("HOLD")
    snap = _snap(held=True, atr=1.0, entry=10.0, px=13.0,
                 exit_signals=[{"type": "OVERBOUGHT", "urgency": "NORMAL"}])
    _resolve_final_action(r, snap, None, True)
    assert r.action == "ADD"


# ═══════════════════════════════════════════════════════════════════
# ② 阈值 / 阻断
# ═══════════════════════════════════════════════════════════════════
def test_pyramid_below_atr_threshold():
    r = _result("HOLD")
    snap = _snap(held=True, atr=1.0, entry=10.0, px=11.0)  # 仅 1×ATR
    _resolve_final_action(r, snap, None, True)
    assert r.action == "HOLD"


def test_pyramid_blocked_by_urgent_exit():
    r = _result("HOLD")
    snap = _snap(held=True, atr=1.0, entry=10.0, px=13.0,
                 exit_signals=[{"type": "MA_BREAKDOWN", "urgency": "URGENT"}])
    _resolve_final_action(r, snap, None, True)
    assert r.action == "HOLD"


def test_pyramid_blocked_by_weekly_bear():
    r = _result("HOLD")
    snap = _snap(held=True, atr=1.0, entry=10.0, px=13.0, weekly="BEAR")
    _resolve_final_action(r, snap, None, True)
    assert r.action == "HOLD"


def test_pyramid_blocked_by_kdj_avoid():
    r = _result("HOLD")
    snap = _snap(held=True, atr=1.0, entry=10.0, px=13.0,
                 macd_kdj={"action": "AVOID_ENTRY"})
    _resolve_final_action(r, snap, None, True)
    assert r.action == "HOLD"


def test_pyramid_blocked_by_game_theory():
    r = _result("HOLD")
    snap = _snap(held=True, atr=1.0, entry=10.0, px=13.0)
    # 现实 gt_advice 必有 action；entry_allowed=False → 金字塔被博弈闸门阻止
    _resolve_final_action(r, snap, _advice(action="HOLD", entry_allowed=False), True)
    assert r.action == "HOLD"


# ═══════════════════════════════════════════════════════════════════
# ③ chase_blocked 豁免 / 语义不变
# ═══════════════════════════════════════════════════════════════════
def test_pyramid_exempt_from_chase_blocked():
    """接近 MM 投影目标位：金字塔加仓豁免 (已有盈利仓加仓)，普通追单仍阻断。"""
    r = _result("HOLD")
    snap = _snap(held=True, atr=1.0, entry=10.0, px=13.0,
                 chase_blocked=True, projected_target=14.0)
    _resolve_final_action(r, snap, None, True)
    assert r.action == "ADD"
    assert any("不受追单限制" in w for w in r.warnings)


def test_chase_blocked_still_blocks_fresh_enter():
    """非金字塔 (未持仓) 时 chase_blocked 仍阻断新仓 ENTER → WAIT。"""
    r = _result("BUY")
    snap = _snap(held=False, atr=1.0, entry=10.0, px=13.0,
                 chase_blocked=True, projected_target=14.0)
    _resolve_final_action(r, snap, None, False)
    assert r.action == "WAIT"


def test_pyramid_respects_sell_priority():
    r = _result("HOLD")
    snap = _snap(held=True, atr=1.0, entry=10.0, px=13.0)
    _resolve_final_action(r, snap, _advice(action="EXIT"), True)
    assert r.action == "EXIT"


def test_no_pyramid_when_not_held():
    r = _result("BUY")
    snap = _snap(held=False, atr=1.0, entry=10.0, px=13.0)
    _resolve_final_action(r, snap, None, False)
    assert r.action == "ENTER"
