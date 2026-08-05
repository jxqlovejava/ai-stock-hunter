# -*- coding: utf-8 -*-
"""tactics 市场状态前置判定 + 跨周期过滤 + MM等距投影测试 (P1-1/P1-5/P1-6)。

覆盖:
  P1-1 ① RANGE 态下金叉被降权      ② BULL 态下金叉正常
  P1-5 ③ 周线方向相反时日线信号降权  +  T+0 收线确认标注
  P1-6 ④ MM 投影目标位计算正确(给定区间)

全部为纯函数/快照级测试, 不触发网络。
"""
import pandas as pd

from src.routing.tactics import (
    TacticalSnapshot,
    _annotate_t0_await_close,
    _apply_cross_period_filter,
    _apply_market_state_gate,
    _apply_projected_target,
    _classify_market_state,
    _compute_mm_projection,
    _mm_projected_target,
    _weekly_direction,
)

SYMBOL = "000001"


def _golden_cross_sig(conf=0.65):
    return {
        "type": "MA_GOLDEN_CROSS", "description": "MA5上穿MA20金叉",
        "zone_low": 10.0, "zone_high": 10.5, "confidence": conf,
    }


def _snap_with_golden_cross():
    snap = TacticalSnapshot(symbol=SYMBOL, name="测试")
    snap.entry_signals.append(_golden_cross_sig())
    snap.best_entry = dict(snap.entry_signals[0])
    return snap


# ═══════════════════════════════════════════════════════════════════
# P1-1 ① RANGE 态下金叉被降权
# ═══════════════════════════════════════════════════════════════════
def test_range_state_downgrades_golden_cross():
    snap = _snap_with_golden_cross()
    _apply_market_state_gate(snap, "RANGE")
    assert snap.entry_signals[0]["confidence"] == round(0.65 * 0.5, 3)
    assert snap.entry_signals[0].get("market_gate") == "RANGE"
    assert snap.best_entry["confidence"] == round(0.65 * 0.5, 3)
    assert snap.notes  # 有 [P1-1] 说明


def test_range_state_keeps_exit_signal_for_display():
    """RANGE 态下出场信号保留(仅降权), 不删除 → 风控动作链路不被破坏。"""
    snap = TacticalSnapshot(symbol=SYMBOL, name="测试")
    snap.entry_signals.append(_golden_cross_sig())
    snap.exit_signals.append({
        "type": "MA_BREAKDOWN", "description": "跌破MA20",
        "exit_zone_low": 10.0, "exit_zone_high": 10.3,
        "confidence": 0.55, "urgency": "NORMAL",
    })
    _apply_market_state_gate(snap, "RANGE")
    # 信号仍存在 → _resolve_final_action 的 REDUCE/CLOSE 判断不受影响
    assert len(snap.exit_signals) == 1
    assert snap.exit_signals[0]["type"] == "MA_BREAKDOWN"
    assert snap.exit_signals[0]["confidence"] == round(0.55 * 0.5, 3)


# ═══════════════════════════════════════════════════════════════════
# P1-1 ② BULL 态下金叉正常
# ═══════════════════════════════════════════════════════════════════
def test_bull_state_keeps_golden_cross_unchanged():
    snap = _snap_with_golden_cross()
    _apply_market_state_gate(snap, "BULL_TRENDING")
    assert snap.entry_signals[0]["confidence"] == 0.65
    assert "market_gate" not in snap.entry_signals[0]
    assert snap.best_entry["confidence"] == 0.65
    assert not snap.notes


def test_bear_state_keeps_signals_unchanged():
    snap = _snap_with_golden_cross()
    _apply_market_state_gate(snap, "BEAR_TRENDING")
    assert snap.entry_signals[0]["confidence"] == 0.65


# ═══════════════════════════════════════════════════════════════════
# P1-5 ③ 周线方向相反时日线信号降权
# ═══════════════════════════════════════════════════════════════════
def test_weekly_bear_downgrades_daily_bull_signal():
    snap = _snap_with_golden_cross()
    _apply_cross_period_filter(snap, "BEAR")
    assert snap.entry_signals[0]["confidence"] == round(0.65 * 0.5, 3)
    assert snap.entry_signals[0].get("market_gate") == "WEEKLY_BEAR_DIVERGE"
    assert snap.best_entry["confidence"] == round(0.65 * 0.5, 3)


def test_weekly_bull_downgrades_daily_exit_signal():
    snap = TacticalSnapshot(symbol=SYMBOL, name="测试")
    snap.exit_signals.append({
        "type": "MA_BREAKDOWN", "description": "跌破MA20",
        "exit_zone_low": 10.0, "exit_zone_high": 10.3,
        "confidence": 0.55, "urgency": "NORMAL",
    })
    _apply_cross_period_filter(snap, "BULL")
    assert snap.exit_signals[0]["confidence"] == round(0.55 * 0.5, 3)


def test_weekly_neutral_leaves_signals_unchanged():
    snap = _snap_with_golden_cross()
    _apply_cross_period_filter(snap, "neutral")
    assert snap.entry_signals[0]["confidence"] == 0.65
    assert "market_gate" not in snap.entry_signals[0]


def test_weekly_direction_downtrend_bear():
    idx = pd.date_range("2024-01-01", periods=300, freq="D")
    closes = [float(200 - i * 0.2) for i in range(300)]
    df = pd.DataFrame({
        "open": [c + 0.1 for c in closes],
        "high": [c + 1.0 for c in closes],
        "low": [c - 1.0 for c in closes],
        "close": closes,
    }, index=idx)
    assert _weekly_direction(df) == "BEAR"


def test_annotate_t0_await_close_appends_note():
    """T+0 收线确认: 最新分时K线未收线 → 提示待收线, 且激进建议被降温。"""
    from datetime import datetime, timedelta
    now = datetime.now()

    class _Bar:
        timestamp = now  # 当前分钟 → 未收线

    t0 = {"action": "BUY", "advice": "金叉买点"}
    _annotate_t0_await_close(t0, [_Bar()])
    assert "notes" in t0
    assert any("未收线" in n for n in t0["notes"])
    assert "待分时收线确认" in t0["advice"]

    # 已收线 (上一分钟) → 不追加
    t0_closed = {"action": "BUY", "advice": "x"}

    class _BarClosed:
        timestamp = now - timedelta(minutes=1)

    _annotate_t0_await_close(t0_closed, [_BarClosed()])
    assert "notes" not in t0_closed

    # 非 dict (数据缺失) → 不抛错
    _annotate_t0_await_close(None, None)


# ═══════════════════════════════════════════════════════════════════
# P1-6 ④ MM 投影目标位计算正确
# ═══════════════════════════════════════════════════════════════════
def test_mm_projection_formula():
    assert _mm_projected_target(10.0, 12.0, "up") == 14.0      # 12 + 2
    assert _mm_projected_target(10.0, 12.0, "down") == 8.0     # 10 - 2
    assert _mm_projected_target(10.0, 12.0, "sideways") is None
    assert _mm_projected_target(0.0, 0.0, "up") is None


def test_mm_projection_from_zhongshu():
    cs = {
        "last_zs": {"zg": 12.0, "zd": 10.0, "zz": 11.0},
        "current_state": {"position": "中枢上方", "zhongshu_state": "延伸"},
    }
    proj = _compute_mm_projection(
        cs, highs=[12.0], lows=[10.0], closes=[11.0, 12.5],
        current_price=12.5, suggested_stop=11.8,
    )
    assert proj is not None
    assert proj["target"] == 14.0
    assert proj["direction"] == "up"
    assert proj["height"] == 2.0
    assert proj["rr_ratio"] is not None


def test_mm_projection_fallback_recent_range():
    closes = [float(100 + i * 0.1) for i in range(60)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    proj = _compute_mm_projection(None, highs, lows, closes, current_price=105.0)
    assert proj is not None
    lo, hi = min(lows), max(highs)
    assert proj["target"] == round(hi + (hi - lo), 2)
    assert proj["direction"] == "up"


def test_apply_projected_target_chase_block_near_target():
    snap = TacticalSnapshot(symbol=SYMBOL, name="测试")
    proj = {"target": 14.0, "direction": "up", "note": ""}
    _apply_projected_target(snap, proj, current_price=13.9)   # 距目标 0.7% → 不追单
    assert snap.projected_target == 14.0
    assert snap.chase_blocked is True

    snap2 = TacticalSnapshot(symbol=SYMBOL, name="测试")
    _apply_projected_target(snap2, proj, current_price=12.0)  # 距目标 16% → 正常
    assert snap2.projected_target == 14.0
    assert snap2.chase_blocked is False


def test_apply_projected_target_preserves_existing_stop():
    """MM 投影不覆盖既有 suggested_stop / atr_stop / target_prices。"""
    snap = TacticalSnapshot(symbol=SYMBOL, name="测试")
    snap.suggested_stop = 9.8
    snap.atr_stop = 9.5
    snap.target_prices = [11.0, 12.0]
    proj = {"target": 14.0, "direction": "up", "note": ""}
    _apply_projected_target(snap, proj, current_price=12.0)
    assert snap.suggested_stop == 9.8
    assert snap.atr_stop == 9.5
    assert snap.target_prices == [11.0, 12.0]
    assert snap.projected_target == 14.0


# ═══════════════════════════════════════════════════════════════════
# P1-1 市场状态三态分类 (RegimeClassifier + Hurst/Choppiness 投票)
# ═══════════════════════════════════════════════════════════════════
def _uptrend():
    closes = [float(100 + i) for i in range(60)]
    return closes, [c + 0.5 for c in closes], [c - 0.5 for c in closes]


def _downtrend():
    closes = [float(200 - i) for i in range(60)]
    return closes, [c + 0.5 for c in closes], [c - 0.5 for c in closes]


def _choppy():
    closes = [103.0 if i % 2 == 0 else 97.0 for i in range(60)]
    return closes, [c + 0.5 for c in closes], [c - 0.5 for c in closes]


def test_classify_uptrend_bull():
    closes, highs, lows = _uptrend()
    detail = _classify_market_state(closes, highs, lows, None, [], None)
    assert detail["state"] == "BULL_TRENDING"
    assert detail["basis"] == "index"
    assert 0.3 <= detail["confidence"] <= 0.9


def test_classify_downtrend_bear():
    closes, highs, lows = _downtrend()
    detail = _classify_market_state(closes, highs, lows, None, [], None)
    assert detail["state"] == "BEAR_TRENDING"


def test_classify_choppy_range():
    closes, highs, lows = _choppy()
    detail = _classify_market_state(closes, highs, lows, None, [], None)
    assert detail["state"] == "RANGE"


def test_classify_risk_on_breadth_without_trend_is_range():
    """高宽度(RISK_ON)但无趋势强度 → RANGE (不启用趋势跟随信号, 保守降权)。"""
    closes, highs, lows = _choppy()
    detail = _classify_market_state(closes, highs, lows, breadth=70.0, stock_close_series=[], chanlun_summary=None)
    assert detail["state"] == "RANGE"


def test_classify_fallback_to_stock_bars():
    closes, _, _ = _uptrend()
    detail = _classify_market_state(None, None, None, None, closes, None)
    assert detail["basis"] == "stock"
    assert detail["state"] == "BULL_TRENDING"


def test_classify_insufficient_data_default_range():
    detail = _classify_market_state([100.0], None, None, None, [], None)
    assert detail["state"] == "RANGE"
    assert detail["basis"] == "index"
