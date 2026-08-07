# -*- coding: utf-8 -*-
"""VWAP 成本带模块测试 — 偏离计算 / 真突破 / 诱多 / 成本带收窄。"""
import numpy as np
import pandas as pd

from src.analysis.vwap_band import (
    band_vs_ma,
    compute_vwap_band,
    detect_vwap_events,
)


def _make_df(n=60, close=None, volume=None, seed=42):
    rng = np.random.default_rng(seed)
    if close is None:
        close = 100 + np.cumsum(rng.normal(0, 1, n))
    close = np.asarray(close, dtype=float)
    if volume is None:
        volume = np.full(n, 1e6)
    high = close + 1.0
    low = close - 1.0
    open_ = close + rng.normal(0, 0.3, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": volume}, index=idx)


# ── 1. 偏离计算 ──
def test_compute_vwap_band_basic():
    """现价高于 VWAP20 → 正偏离；成本带上下轨正确。"""
    df = _make_df()
    res = compute_vwap_band(df, price=110.0)
    assert res.vwap20 > 0
    # 现价 110 高于近期成本 → 正偏离
    assert res.price_vs_vwap20 > 0
    assert res.band_high >= res.band_low
    assert res.band_position in ("上轨上方", "带内", "下轨下方")


def test_compute_vwap_band_below():
    """现价低于 VWAP20 → 负偏离。"""
    df = _make_df()
    res = compute_vwap_band(df, price=80.0)
    assert res.price_vs_vwap20 < 0
    assert res.position_vs_vwap == "VWAP下方"


def test_compute_vwap_band_data_gap():
    """空 DataFrame → DATA_GAP 标记，不崩溃。"""
    res = compute_vwap_band(pd.DataFrame(), price=100.0)
    assert res.vwap20 == 0.0
    assert "DATA_GAP" in res.summary


def test_compute_vwap_band_chinese_columns():
    """中文列名输入正确映射（腾讯/mootdx 源）。"""
    df = _make_df().rename(columns={
        "open": "开盘", "high": "最高", "low": "最低",
        "close": "收盘", "volume": "成交量",
    })
    res = compute_vwap_band(df, price=110.0)
    assert res.vwap20 > 0


# ── 2. 真突破检测 ──
def test_detect_vwap_events_breakout():
    """价格从下方放量穿越 VWAP → 真突破信号。

    构造：55 根横盘 95（VWAP≈95），1 根缩量小跌到 94（VWAP 下方），
    1 根放量涨到 98（穿越 VWAP 上方）。prev_close<VWAP<curr → 真突破。
    """
    close = [95.0] * 55 + [94.0] + [98.0]
    volume = [1e6] * 55 + [0.8e6] + [3.5e6]
    df = _make_df(n=len(close), close=close, volume=volume)
    signals = detect_vwap_events(df, price=98.0)
    assert any(s.direction == "bull" and "放量站上VWAP" in s.description
               for s in signals), f"signals={signals}"


# ── 3. 诱多检测 ──
def test_detect_vwap_events_lure():
    """VWAP 上方价涨量缩 → 诱多信号。

    构造：45 根横盘 100，10 根放量拉升到 112（站稳 VWAP 上方），
    2 根高位微涨但量大幅萎缩（最近 3 日量 << 前 5 日量）→ 诱多。
    """
    close = [100.0] * 45 + list(np.linspace(100, 112, 10)) + [112.5, 113.0]
    volume = [3e6] * 45 + [3.5e6] * 10 + [1e6, 1e6]
    df = _make_df(n=len(close), close=close, volume=volume)
    signals = detect_vwap_events(df, price=113.0)
    assert any(s.direction == "bear" and "价涨量缩" in s.description
               for s in signals), f"signals={signals}"


def test_detect_vwap_events_no_signal_short():
    """数据不足 20 根 → 无信号。"""
    df = _make_df(10)
    assert detect_vwap_events(df, price=100.0) == []


# ── 4. 成本带收窄 ──
def test_band_vs_ma_narrow():
    """VWAP 与 MA 收敛 → 带宽窄（变盘提示）。"""
    # 高度横盘：close 恒定 → VWAP≈MA → 带宽极小
    df = _make_df(close=np.full(60, 100.0))
    res = band_vs_ma(df, price=100.5)
    assert res.band_range < 3.0
    assert res.band_position == "上轨上方"  # 现价 100.5 > band_high 100
    # band_vs_ma 组合了事件检测
    assert isinstance(res.signals, list)


def test_band_vs_ma_passes_symbol():
    """band_vs_ma 透传 symbol/name。"""
    df = _make_df()
    res = band_vs_ma(df, price=110.0, symbol="000001", name="测试")
    assert res.symbol == "000001"
    assert res.name == "测试"


def test_vwap60_requires_60_bars():
    """不足 60 根 → vwap60 为 0，不崩溃。"""
    df = _make_df(40)
    res = compute_vwap_band(df, price=105.0)
    assert res.vwap20 > 0
    assert res.vwap60 == 0.0
