# -*- coding: utf-8 -*-
from src.indicators.chanlun.core.fractal import detect_fractals
from src.indicators.chanlun.core.merge import merge_bars, MergedBar
import pandas as pd


def _merged(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    return merge_bars(df)


def test_top_fractal():
    merged = _merged([(8, 9, 7, 8), (9, 11, 8.5, 10.5), (10, 10.5, 8, 10)])
    fs = detect_fractals(merged)
    assert len(fs) == 1
    assert fs[0].mark == "G"
    assert fs[0].fx == 11.0


def test_bottom_fractal():
    merged = _merged([(9, 10, 8, 9.5), (8, 8.5, 6.5, 7), (7.5, 9, 7, 7.8)])
    fs = detect_fractals(merged)
    assert len(fs) == 1
    assert fs[0].mark == "D"
    assert fs[0].fx == 6.5


def test_flat_middle_no_fractal():
    # 中间根与左右等高 → 平盘不误判
    merged = _merged([(8, 10, 7, 9), (9, 10, 8, 9.5), (9.5, 11, 8.5, 10)])
    fs = detect_fractals(merged)
    assert len(fs) == 0


def test_flat_middle_no_fractal_direct():
    # 绕过 merge_bars 直接构造等高中间根的 merged 列表，真正覆盖"平盘不误判"严格比较分支
    merged = [
        MergedBar(0, pd.Timestamp("2026-01-01"), 10.0, 7.0, "up"),
        MergedBar(1, pd.Timestamp("2026-01-02"), 10.0, 8.0, "up"),   # 中间 high 与左等高
        MergedBar(2, pd.Timestamp("2026-01-03"), 10.0, 8.5, "up"),   # 与右也等高
    ]
    assert detect_fractals(merged) == []


def test_insufficient_bars():
    merged = _merged([(8, 9, 7, 8), (9, 10, 8, 9)])
    assert detect_fractals(merged) == []
