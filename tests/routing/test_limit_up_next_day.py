# -*- coding: utf-8 -*-
"""P1-8 涨停次日行为 + 位置解读 (文章共识 @LuBtc888 涨停次日低开)。

覆盖:
  _limit_up_next_day_signal
    ① 高位涨停次日低开 → distribute_warning (出货预警)
    ② 底部涨停次日低开 → accumulate_watch (吸筹观察)
    ③ 前日无涨停 → prev_limit_up=False (无信号)
    ④ 创业板 20% 涨停阈值识别
  _apply_limit_up_next_day
    ⑤ distribute_warning → 入场信号降权 + 出场信号
    ⑥ accumulate_watch → 观察级入场信号

全部为纯函数测试, 不触发网络。
"""
import pandas as pd

from src.routing.tactics import (
    TacticalSnapshot,
    _apply_limit_up_next_day,
    _limit_up_next_day_signal,
)


def _mk_df(closes, start="2023-01-02"):
    """构造日线 DataFrame（RangeIndex + date 列，模拟真实数据源）。"""
    idx = pd.date_range(start, periods=len(closes), freq="B")
    closes = [float(c) for c in closes]
    return pd.DataFrame({
        "date": idx,
        "open": [c * 0.99 for c in closes],
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * len(closes),
    })


def test_high_position_limit_up_next_day_gap_down_is_distribute_warning():
    """① 高位涨停次日低开 → 出货预警。"""
    closes = [100 + i * 0.7 for i in range(137)]      # 缓涨到高位
    closes.append(round(closes[-1] * 1.1, 2))         # 涨停日 (bar -2)
    closes.append(round(closes[-1] * 0.99, 2))        # 今日低开 (bar -1)
    df = _mk_df(closes)
    out = _limit_up_next_day_signal(df, symbol="000001")

    assert out["prev_limit_up"] is True
    assert out["gap_direction"] == "down"
    assert out["position"] == "high"
    assert out["signal"] == "distribute_warning"


def test_low_position_limit_up_next_day_gap_down_is_accumulate_watch():
    """② 底部涨停次日低开 → 吸筹观察。"""
    closes = [200 - i * 0.7 for i in range(137)]      # 缓跌到底部
    closes.append(round(closes[-1] * 1.1, 2))         # 涨停日 (bar -2)
    closes.append(round(closes[-1] * 0.99, 2))        # 今日低开 (bar -1)
    df = _mk_df(closes)
    out = _limit_up_next_day_signal(df, symbol="000001")

    assert out["prev_limit_up"] is True
    assert out["gap_direction"] == "down"
    assert out["position"] == "low"
    assert out["signal"] == "accumulate_watch"


def test_no_limit_up_prev_day_returns_no_signal():
    """③ 前日无涨停 → 无信号。"""
    closes = [100 + i * 0.05 for i in range(60)]      # 平缓爬升
    df = _mk_df(closes)
    out = _limit_up_next_day_signal(df, symbol="000001")

    assert out["prev_limit_up"] is False
    assert out["signal"] == ""


def test_chinext_20pct_limit_up_threshold():
    """④ 创业板 20% 涨停阈值：前日 +19.6% 视为涨停。"""
    closes = [100 + i * 0.05 for i in range(137)]
    closes.append(round(closes[-1] * 1.196, 2))       # 创业板涨停日 (bar -2)
    closes.append(round(closes[-1] * 0.99, 2))        # 今日低开 (bar -1)
    df = _mk_df(closes)
    out = _limit_up_next_day_signal(df, symbol="300001")

    assert out["prev_limit_up"] is True


def test_apply_distribute_warning_degrades_entry_and_adds_exit():
    """⑤ distribute_warning → 入场信号降权 + 出场预警。"""
    snapshot = TacticalSnapshot(symbol="000001", name="测试")
    snapshot.entry_signals = [
        {"type": "BREAKOUT", "confidence": 0.7, "zone_low": 10, "zone_high": 11},
    ]
    signal = {
        "prev_limit_up": True, "gap_direction": "down", "position": "high",
        "signal": "distribute_warning",
        "note": "高位涨停次日低开 — 出货嫌疑",
    }
    _apply_limit_up_next_day(snapshot, signal)

    assert snapshot.entry_signals[0]["confidence"] < 0.5
    assert snapshot.entry_signals[0]["market_gate"] == "LIMIT_UP_NEXT_DAY_DISTRIBUTE"
    assert any(s["type"] == "LIMIT_UP_NEXT_DAY_DISTRIBUTE" for s in snapshot.exit_signals)
    assert any("[P1-8]" in n for n in snapshot.notes)


def test_apply_accumulate_watch_adds_entry_signal():
    """⑥ accumulate_watch → 观察级入场信号。"""
    snapshot = TacticalSnapshot(symbol="000001", name="测试")
    signal = {
        "prev_limit_up": True, "gap_direction": "down", "position": "low",
        "signal": "accumulate_watch",
        "note": "底部涨停次日低开 — 洗盘吸筹",
    }
    _apply_limit_up_next_day(snapshot, signal)

    assert any(s["type"] == "LIMIT_UP_ACCUMULATE" for s in snapshot.entry_signals)
