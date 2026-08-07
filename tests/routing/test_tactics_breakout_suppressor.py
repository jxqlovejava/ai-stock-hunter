# -*- coding: utf-8 -*-
"""tactics P1-7 周线突破结构 — 追突破抑制 / 回踩二波 / 锁利降权 (2026-08-07 回测验证)。

覆盖:
  P1-7 ① 周线放量突破刚发生 → 趋势跟随入场信号 ×0.5 + WEEKLY_BREAKOUT_SUPPRESS
        ② 锁利条件(涨≥20%+MA5死叉) → 全部入场信号 ×0.5 + LOCK_PROFIT
        ③ 突破后回踩缩量企稳 → 仅标注, 不降权 (二波入场确认)
  结构判定 ④ _weekly_breakout_structure 三种场景 flag 正确

全部为纯函数/快照级测试, 不触发网络。
"""
import numpy as np
import pandas as pd

from src.routing.tactics import (
    TacticalSnapshot,
    _apply_breakout_chase_suppressor,
    _enhance_market_state,
    _weekly_breakout_structure,
)

SYMBOL = "000001"


def _mk_df(closes, volumes=None, start="2023-01-02"):
    """构造日线 DataFrame（含 date 列 + RangeIndex，模拟真实数据源）。"""
    idx = pd.date_range(start, periods=len(closes), freq="B")
    closes = [float(c) for c in closes]
    if volumes is None:
        volumes = [1_000_000.0] * len(closes)
    return pd.DataFrame({
        "date": idx,
        "open": [c * 0.99 for c in closes],
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "close": closes,
        "volume": [float(v) for v in volumes],
    })


def _flat_weeks(n_weeks, px=100.0, vol=1_000_000.0, rise_to=None):
    """n_weeks 周平盘（每周5个交易日）。rise_to 非空时在本段内线性爬升至目标。"""
    rows = []
    steps = max(1, n_weeks - 1)
    for w in range(n_weeks):
        cur = px
        if rise_to is not None:
            cur = px + (rise_to - px) * (w / steps)
        for _ in range(5):
            rows.append((cur, vol))
    return rows


def _golden_cross_sig(conf=0.65):
    return {
        "type": "MA_GOLDEN_CROSS", "description": "MA5上穿MA20金叉",
        "zone_low": 10.0, "zone_high": 10.5, "confidence": conf,
    }


def _snap_with_signals(*types):
    snap = TacticalSnapshot(symbol=SYMBOL, name="测试")
    for t in types:
        snap.entry_signals.append({
            "type": t, "description": t, "zone_low": 10.0, "zone_high": 10.5,
            "confidence": 0.65,
        })
    snap.best_entry = dict(snap.entry_signals[0])
    return snap


# ═══════════════════════════════════════════════════════════════════
# P1-7 ① 周线放量突破刚发生 → 趋势跟随信号被抑制
# ═══════════════════════════════════════════════════════════════════
def _breakout_df():
    """52周平盘 ~100，最后一周放量拉到 125 → 周线放量突破(26周平台高)。"""
    rows = _flat_weeks(52, px=100.0)
    # 最后一周(5日)放量拉升
    for c in (110.0, 115.0, 120.0, 123.0, 125.0):
        rows.append((c, 3_000_000.0))
    closes = [r[0] for r in rows]
    vols = [r[1] for r in rows]
    return _mk_df(closes, vols)


def test_breakout_structure_flags_fresh_breakout():
    st = _weekly_breakout_structure(_breakout_df())
    assert st["fresh_breakout"] is True
    assert st["pullback_reclaim"] is False
    assert st["lock_profit"] is False
    assert "突破" in st["note"]


def test_fresh_breakout_downgrades_trend_signals():
    snap = _snap_with_signals("MA_GOLDEN_CROSS", "BREAKOUT", "CHANLUN_BUY")
    _apply_breakout_chase_suppressor(snap, {"fresh_breakout": True, "pullback_reclaim": False,
                                            "lock_profit": False, "note": "周线放量突破刚发生"})
    # 趋势跟随类降权
    assert snap.entry_signals[0]["confidence"] == round(0.65 * 0.5, 3)
    assert snap.entry_signals[0]["market_gate"] == "WEEKLY_BREAKOUT_SUPPRESS"
    assert snap.entry_signals[1]["confidence"] == round(0.65 * 0.5, 3)
    # 非趋势跟随(缠论)不受影响
    assert snap.entry_signals[2]["confidence"] == 0.65
    assert "market_gate" not in snap.entry_signals[2]
    assert snap.best_entry["confidence"] == round(0.65 * 0.5, 3)
    assert any("[P1-7]" in n for n in snap.notes)


# ═══════════════════════════════════════════════════════════════════
# P1-7 ② 锁利条件 → 全部入场信号降权
# ═══════════════════════════════════════════════════════════════════
def _lock_profit_df():
    """48周平盘100 → 9周爬升至130 → 3周横盘130 → 末日跌至125(MA5死叉MA10, 60日涨幅+25%)。"""
    rows = _flat_weeks(48, px=100.0)
    rows += _flat_weeks(9, px=100.0, rise_to=130.0)
    rows += _flat_weeks(3, px=130.0)
    rows.append((125.0, 1_000_000.0))  # 末日回落 → 当日 MA5<MA10 且昨日 MA5>=MA10
    closes = [r[0] for r in rows]
    vols = [r[1] for r in rows]
    return _mk_df(closes, vols)


def test_lock_profit_structure_flags():
    st = _weekly_breakout_structure(_lock_profit_df())
    assert st["lock_profit"] is True
    assert st["fresh_breakout"] is False


def test_lock_profit_downgrades_all_entry_signals():
    snap = _snap_with_signals("MA_GOLDEN_CROSS", "PULLBACK_SUPPORT", "OVERSOLD_BOUNCE")
    _apply_breakout_chase_suppressor(snap, {"fresh_breakout": False, "pullback_reclaim": False,
                                            "lock_profit": True, "note": "近60日涨≥20%且MA5死叉MA10"})
    for sig in snap.entry_signals:
        assert sig["confidence"] == round(0.65 * 0.5, 3)
        assert sig["market_gate"] == "LOCK_PROFIT"
    assert snap.best_entry["confidence"] == round(0.65 * 0.5, 3)
    assert any("[P1-7]" in n for n in snap.notes)


# ═══════════════════════════════════════════════════════════════════
# P1-7 ③ 突破后回踩缩量企稳 → 仅标注, 不降权
# ═══════════════════════════════════════════════════════════════════
def _pullback_reclaim_df():
    """40周平盘100 → 突破周125(量3M) → 4周回调(量0.8M) → 末周收回112。"""
    rows = _flat_weeks(40, px=100.0)
    for c in (110.0, 118.0, 123.0, 125.0, 125.0):  # 突破周(第41周)
        rows.append((c, 3_000_000.0))
    # 4周回调: 量缩至0.8M, 价格回落到MA10w附近再收回
    pulls = [118.0, 112.0, 108.0, 106.0, 110.0,
             112.0, 108.0, 104.0, 106.0, 108.0,
             110.0, 106.0, 104.0, 103.0, 105.0,
             108.0, 106.0, 107.0, 109.0, 112.0]
    for c in pulls:
        rows.append((c, 0.8_000_000))
    closes = [r[0] for r in rows]
    vols = [r[1] for r in rows]
    return _mk_df(closes, vols)


def test_pullback_reclaim_structure_flags():
    st = _weekly_breakout_structure(_pullback_reclaim_df())
    # 末周: 低点触MA10w带内且收回, 量缩; 突破在4周前(非fresh)
    assert st["pullback_reclaim"] is True
    assert st["fresh_breakout"] is False


def test_pullback_reclaim_annotates_without_downgrade():
    snap = _snap_with_signals("MA_GOLDEN_CROSS")
    _apply_breakout_chase_suppressor(snap, {"fresh_breakout": False, "pullback_reclaim": True,
                                            "lock_profit": False, "note": "突破后回踩MA10周缩量企稳"})
    assert snap.entry_signals[0]["confidence"] == 0.65
    assert "market_gate" not in snap.entry_signals[0]
    assert any("二波" in n for n in snap.notes)


# ═══════════════════════════════════════════════════════════════════
# P1-7 ④ 中性场景: 无任何结构 → 不影响
# ═══════════════════════════════════════════════════════════════════
def _neutral_df():
    """30周平盘无突破无锁利。"""
    rows = _flat_weeks(30, px=100.0)
    return _mk_df([r[0] for r in rows], [r[1] for r in rows])


def test_neutral_structure_no_flags():
    st = _weekly_breakout_structure(_neutral_df())
    assert st["fresh_breakout"] is False
    assert st["pullback_reclaim"] is False
    assert st["lock_profit"] is False
    assert st["note"] == ""


def test_breakout_suppressor_noop_on_empty_structure():
    snap = _snap_with_signals("MA_GOLDEN_CROSS")
    _apply_breakout_chase_suppressor(snap, {})
    assert snap.entry_signals[0]["confidence"] == 0.65
    assert "market_gate" not in snap.entry_signals[0]
    assert not snap.notes


# ═══════════════════════════════════════════════════════════════════
# P1-7 ⑤ 接线: _enhance_market_state 把 daily_df 传给抑制器
# ═══════════════════════════════════════════════════════════════════
def test_enhance_market_state_wires_breakout_suppressor():
    """daily_df 传入 → 抑制器生效: RANGE 门控(×0.5) + 追突破抑制(×0.5) 连乘降权。"""
    snap = _snap_with_signals("MA_GOLDEN_CROSS")
    _enhance_market_state(snap, None, [], None, _breakout_df())
    # 0.65 → RANGE 门控 ×0.5 → 追突破抑制 ×0.5 = 0.1625 → 0.163
    assert snap.entry_signals[0]["confidence"] == round(0.65 * 0.5 * 0.5, 3)
    assert any("P1-7" in n for n in snap.notes)


def test_enhance_market_state_no_daily_df_is_noop():
    """daily_df 缺省 → 抑制器不触发, 不影响原有门控。"""
    snap = _snap_with_signals("MA_GOLDEN_CROSS")
    _enhance_market_state(snap, None, [], None)
    assert not any("P1-7" in n for n in snap.notes)


# ═══════════════════════════════════════════════════════════════════
# P1-7 ⑥ 突破质量子检查 — 四假突破形态 (0xToni 量价帖)
# ═══════════════════════════════════════════════════════════════════
def _failed_breakout_df():
    """40周平盘100 → 突破周125(量3M) → 4周跌回96(破平台)。"""
    rows = _flat_weeks(40, px=100.0)
    for c in (110.0, 118.0, 123.0, 125.0, 125.0):
        rows.append((c, 3_000_000.0))
    for c in (116.0, 112.0, 108.0, 104.0, 100.0, 99.0, 98.0, 97.0,
              96.0, 96.0, 96.0, 96.0, 96.0, 96.0, 96.0, 96.0, 96.0, 96.0, 96.0, 96.0):
        rows.append((c, 1_000_000.0))
    return _mk_df([r[0] for r in rows], [r[1] for r in rows])


def _low_quality_df():
    """40周平盘100 → 突破周 长上影(open100/high130/close102/low99, 量3M) → 放量滞涨。"""
    rows = _flat_weeks(40, px=100.0)
    n = len(rows)
    closes = [r[0] for r in rows] + [102.0] * 5
    vols = [r[1] for r in rows] + [3_000_000.0] * 5
    opens = [r[0] * 0.99 for r in rows] + [100.0] * 5
    highs = [r[0] * 1.02 for r in rows] + [130.0] * 5
    lows = [r[0] * 0.98 for r in rows] + [99.0] * 5
    idx = pd.date_range("2023-01-02", periods=len(closes), freq="B")
    return pd.DataFrame({
        "date": idx, "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": vols,
    })


def _no_follow_df():
    """40周平盘100 → 突破周125(量3M) → 4周120(未创新高, 未破平台)。"""
    rows = _flat_weeks(40, px=100.0)
    for c in (110.0, 118.0, 123.0, 125.0, 125.0):
        rows.append((c, 3_000_000.0))
    for c in (122.0, 121.0, 121.0, 120.0, 120.0, 120.0, 119.0, 119.0,
              120.0, 120.0, 121.0, 120.0, 120.0, 119.0, 120.0, 120.0,
              120.0, 120.0, 120.0, 120.0):
        rows.append((c, 1_000_000.0))
    return _mk_df([r[0] for r in rows], [r[1] for r in rows])


def test_failed_breakout_flag():
    st = _weekly_breakout_structure(_failed_breakout_df())
    assert st["failed_breakout"] is True
    assert st["fresh_breakout"] is False
    assert "突破失败" in st["note"]


def test_low_quality_breakout_flag():
    st = _weekly_breakout_structure(_low_quality_df())
    assert st["low_quality"] is True
    assert st["fresh_breakout"] is True
    assert st["failed_breakout"] is False
    assert "滞涨" in st["note"]


def test_no_follow_through_flag():
    st = _weekly_breakout_structure(_no_follow_df())
    assert st["no_follow_through"] is True
    assert st["failed_breakout"] is False
    assert st["fresh_breakout"] is False
    assert "未创新高" in st["note"]


def test_failed_breakout_downgrades_trend_signals():
    """突破失败 → 趋势跟随信号降权 + BREAKOUT_FAILED 标签。"""
    snap = _snap_with_signals("MA_GOLDEN_CROSS", "CHANLUN_BUY")
    _apply_breakout_chase_suppressor(snap, {
        "fresh_breakout": False, "failed_breakout": True,
        "low_quality": False, "no_follow_through": True,
        "pullback_reclaim": False, "lock_profit": False, "note": "突破失败: 跌回突破平台下方",
    })
    assert snap.entry_signals[0]["confidence"] == round(0.65 * 0.5, 3)
    assert snap.entry_signals[0]["market_gate"] == "BREAKOUT_FAILED"
    assert snap.entry_signals[1]["confidence"] == 0.65  # 缠论不受影响
    assert any("突破失败" in n for n in snap.notes)


def test_high_quality_reclaim_not_suppressed():
    """回踩缩量企稳(二波) 且无失败/低质 → 不降权。"""
    snap = _snap_with_signals("MA_GOLDEN_CROSS")
    _apply_breakout_chase_suppressor(snap, {
        "fresh_breakout": False, "failed_breakout": False,
        "low_quality": False, "no_follow_through": False,
        "pullback_reclaim": True, "lock_profit": False, "note": "突破后回踩MA10周缩量企稳",
    })
    assert snap.entry_signals[0]["confidence"] == 0.65
    assert "market_gate" not in snap.entry_signals[0]
    assert any("二波" in n for n in snap.notes)
