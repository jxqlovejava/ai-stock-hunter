# -*- coding: utf-8 -*-
"""主力抢筹形态参考信号 (借鉴自媒体《一种模式1万遍之：主力抢筹》T3)。

覆盖:
  _main_force_accumulate_signal
    ① 低位放量冲高回落大阳 → accumulate_start (建仓)
    ② 低位缩量小K → washout (洗盘)
    ③ 低位连续5日小阳 → accumulate_stealth (偷偷加仓)
    ④ 回踩MA8企稳 + 倍量突破左高 → breakout (上车点)
    ⑤ 高位放量滞涨 → distribution (出货警告)
    ⑥ 无明显形态 → 不触发
  _apply_main_force_accumulate
    ⑦ 只加 notes；breakout 才加低置信入场信号，不改已有评分

全部纯函数测试，无网络。
"""
import pandas as pd

from src.routing.tactics import (
    TacticalSnapshot,
    _apply_main_force_accumulate,
    _main_force_accumulate_signal,
)


def _mk_df(closes, volumes, start="2023-01-02", open_pct=0.99, high_pct=1.02, low_pct=0.98):
    """构造日线 DataFrame（含 date/open/high/low/close/volume）。"""
    idx = pd.date_range(start, periods=len(closes), freq="B")
    closes = [float(c) for c in closes]
    volumes = [float(v) for v in volumes]
    return pd.DataFrame({
        "date": idx,
        "open": [c * open_pct for c in closes],
        "high": [c * high_pct for c in closes],
        "low": [c * low_pct for c in closes],
        "close": closes,
        "volume": volumes,
    })


def _flat(n=35, price=10.0, vol=1_000_000.0):
    """高位 10 → 低位 6 的下跌序列（低位判定需 60 日高点足够高，当前价在低位）。"""
    closes = [price - i * (price - price * 0.6) / n for i in range(n)]  # 10 → 6
    return closes


def test_accumulate_start_low_position_volume_spike_rejection():
    """① 低位放量冲高回落大阳 → 建仓。"""
    closes = _flat(35)  # 高位 10 → 低位 ~6
    # 今日: 大阳 + 长上影 + 放量
    today_open = closes[-1]
    today_close = today_open * 1.05
    today_high = today_close * 1.08
    closes.append(today_close)
    vols = [1_000_000.0] * 35 + [5_000_000.0]
    df = _mk_df(closes, vols, open_pct=1.0)
    # 手动覆盖最后一根 K 线形态
    df.loc[df.index[-1], "open"] = today_open
    df.loc[df.index[-1], "high"] = today_high
    out = _main_force_accumulate_signal(df, symbol="600519")
    assert out["matched"] and out["stage"] == "accumulate_start"
    assert out["confidence"] > 0


def test_washout_shrinking_volume_small_bodies():
    """② 低位缩量小K → 洗盘。"""
    closes = _flat(35)  # 低位 ~6
    for _ in range(3):
        closes.append(closes[-1] * 1.002)  # 小阳
    vols = [1_000_000.0] * 35 + [300_000.0, 250_000.0, 280_000.0]
    df = _mk_df(closes, vols, open_pct=0.998, high_pct=1.005, low_pct=0.995)
    out = _main_force_accumulate_signal(df, symbol="600519")
    assert out["matched"] and out["stage"] == "washout"


def test_accumulate_stealth_five_small_yang():
    """③ 低位连续5日小阳 → 偷偷加仓。"""
    base = _flat(30)  # 低位 ~6
    # 5 连小阳上行
    last = base[-1]
    for i in range(5):
        last = last * 1.01
        base.append(last)
    vols = [1_000_000.0] * len(base)
    df = _mk_df(base, vols, open_pct=0.995, high_pct=1.01, low_pct=0.99)
    out = _main_force_accumulate_signal(df, symbol="600519")
    assert out["matched"] and out["stage"] == "accumulate_stealth"


def test_breakout_volume_spike_above_left_high():
    """④ 回踩MA8企稳 + 倍量突破左高 → 上车点。"""
    # 先涨到高点 ~8，再回调到 MA8 附近，今日倍量突破
    closes = [6 + i * 0.05 for i in range(40)]  # 涨到 ~8
    left_high = closes[-1]
    for _ in range(5):
        closes.append(closes[-1] * 0.99)  # 回踩 ~5 日
    closes.append(left_high * 1.05)  # 今日倍量突破
    vols = [1_000_000.0] * (len(closes) - 1) + [3_000_000.0]
    df = _mk_df(closes, vols, open_pct=0.99, high_pct=1.01, low_pct=0.985)
    out = _main_force_accumulate_signal(df, symbol="600519")
    assert out["matched"] and out["stage"] == "breakout"
    assert out["breakout_price"] == closes[-1]


def test_distribution_high_position_flat_on_volume():
    """⑤ 高位放量滞涨 → 出货警告。"""
    closes = [13.4] * 35  # 高位横盘（无新高 → 不会误判 breakout）
    closes.append(13.4)  # 今日滞涨
    vols = [1_000_000.0] * 35 + [2_000_000.0]
    df = _mk_df(closes, vols, open_pct=0.999, high_pct=1.005, low_pct=0.995)
    out = _main_force_accumulate_signal(df, symbol="600519")
    assert out["matched"] and out["stage"] == "distribution"


def test_no_signal_on_flat_quiet_data():
    """⑥ 平静横盘 → 不触发。"""
    closes = [10.0] * 35
    vols = [1_000_000.0] * 35
    df = _mk_df(closes, vols, open_pct=1.0, high_pct=1.001, low_pct=0.999)
    out = _main_force_accumulate_signal(df, symbol="600519")
    assert not out["matched"]


def test_short_data_returns_none():
    """数据不足 30 根 → 不触发。"""
    df = _mk_df([10.0] * 10, [1_000_000.0] * 10)
    out = _main_force_accumulate_signal(df, symbol="600519")
    assert not out["matched"]


def test_apply_accumulate_start_only_notes():
    """⑦a 建仓信号只加 notes，不加入场信号。"""
    snap = TacticalSnapshot(symbol="600519", name="茅台")
    signal = {
        "matched": True, "stage": "accumulate_start",
        "description": "低位放量冲高回落大阳 — 主力建仓信号", "confidence": 0.55,
    }
    _apply_main_force_accumulate(snap, signal)
    assert any("主力抢筹" in n for n in snap.notes)
    assert snap.entry_signals == []


def test_apply_breakout_adds_low_conf_entry_signal():
    """⑦b 突破上车点加低置信入场信号，不覆盖已有信号。"""
    snap = TacticalSnapshot(symbol="600519", name="茅台")
    snap.entry_signals.append({
        "type": "EXISTING", "description": "已有信号", "confidence": 0.8,
    })
    signal = {
        "matched": True, "stage": "breakout",
        "description": "回踩MA8企稳+倍量突破左高 — 上车点",
        "confidence": 0.6, "breakout_price": 8.4,
    }
    _apply_main_force_accumulate(snap, signal)
    # 已有信号未被改动
    assert snap.entry_signals[0]["confidence"] == 0.8
    # 新入场信号为低置信
    added = snap.entry_signals[-1]
    assert added["type"] == "MAIN_FORCE_BREAKOUT"
    assert added["confidence"] == 0.4
