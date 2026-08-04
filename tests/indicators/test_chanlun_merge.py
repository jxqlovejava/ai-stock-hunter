# -*- coding: utf-8 -*-
import pandas as pd

from src.indicators.chanlun.core.merge import merge_bars


def _make_df(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def test_up_direction_merge_takes_larger():
    df = _make_df([
        (8, 9, 7, 8.5),        # [7,9]  首根
        (8.5, 10, 8, 9),       # [8,10] 无包含, high↑ → direction=up
        (9, 9.5, 8.5, 9.2),    # [8.5,9.5] 被 [8,10] 包含 → 取较大高/较大低
    ])
    merged = merge_bars(df)
    assert len(merged) == 2            # 3 根合并为 2
    assert merged[-1].high == 10.0     # max(10, 9.5)
    assert merged[-1].low == 8.5       # max(8, 8.5)
    assert merged[-1].direction == "up"


def test_down_direction_merge_takes_smaller():
    df = _make_df([
        (10, 12, 9, 10.5),     # [9,12] 首根
        (9.5, 10.5, 8.5, 9),   # [8.5,10.5] 无包含, high↓ → direction=down
        (9, 9.5, 8.8, 9.2),    # [8.8,9.5] 被 [8.5,10.5] 包含 → 取较小高/较小低
    ])
    merged = merge_bars(df)
    assert len(merged) == 2
    assert merged[-1].high == 9.5      # min(10.5, 9.5)
    assert merged[-1].low == 8.5       # min(8.5, 8.8)
    assert merged[-1].direction == "down"


def test_no_containment_keeps_all_bars():
    df = _make_df([
        (8, 9, 7, 8.5), (8.5, 10, 8, 9), (9, 11, 8.8, 10.5),
    ])
    merged = merge_bars(df)
    assert len(merged) == 3
    assert merged[-1].direction == "up"


def test_empty_df_returns_empty():
    df = _make_df([])
    assert merge_bars(df) == []


def test_partial_overlap_not_merged():
    # 前根 [10,12], 当前 [7,9] → 当前整体低于前根, 非包含 → 不合并（回归 Bug1）
    df = _make_df([(10, 12, 9, 10.5), (8, 9, 7, 8)])
    merged = merge_bars(df)
    assert len(merged) == 2
