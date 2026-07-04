"""Tests for Threshold signal."""

import pandas as pd

from oxq.signals.threshold import Threshold


def _make_df(values: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=len(values))
    return pd.DataFrame({"close": values, "rsi": values}, index=idx)


def test_threshold_gt():
    sig = Threshold()
    result = sig.compute(_make_df([10, 30, 70, 80, 50]), column="rsi", threshold=60.0, relationship="gt")
    expected = [False, False, True, True, False]
    assert list(result) == expected


def test_threshold_lt():
    sig = Threshold()
    result = sig.compute(_make_df([10, 30, 70, 80, 50]), column="rsi", threshold=40.0, relationship="lt")
    expected = [True, True, False, False, False]
    assert list(result) == expected


def test_threshold_gte():
    sig = Threshold()
    result = sig.compute(_make_df([10, 60, 70]), column="rsi", threshold=60.0, relationship="gte")
    expected = [False, True, True]
    assert list(result) == expected


def test_threshold_lte():
    sig = Threshold()
    result = sig.compute(_make_df([10, 60, 70]), column="rsi", threshold=60.0, relationship="lte")
    expected = [True, True, False]
    assert list(result) == expected


def test_threshold_per_symbol():
    idx = pd.bdate_range("2024-01-01", periods=3)
    df_a = pd.DataFrame({"rsi": [10, 80, 50]}, index=idx)
    df_b = pd.DataFrame({"rsi": [90, 20, 60]}, index=idx)
    result_a = Threshold().compute(df_a, column="rsi", threshold=50.0, relationship="gt")
    result_b = Threshold().compute(df_b, column="rsi", threshold=50.0, relationship="gt")
    assert list(result_a) == [False, True, False]
    assert list(result_b) == [True, False, True]


def test_threshold_has_name():
    assert Threshold().name == "Threshold"
