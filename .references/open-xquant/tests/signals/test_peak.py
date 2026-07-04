"""Tests for Peak signal."""

import pandas as pd

from oxq.signals.peak import Peak


def _make_df(values: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=len(values))
    return pd.DataFrame({"close": values}, index=idx)


def test_peak_detects_local_max():
    # order=1: a peak is higher than its immediate neighbors
    result = Peak().compute(_make_df([10, 20, 15, 25, 10]), column="close", kind="peak", order=1)
    assert list(result) == [False, True, False, True, False]


def test_trough_detects_local_min():
    result = Peak().compute(_make_df([20, 10, 25, 5, 15]), column="close", kind="trough", order=1)
    assert list(result) == [False, True, False, True, False]


def test_peak_order_2():
    # order=2: must be higher than 2 neighbors on each side
    # index 2 (value 30): 30 > 10,15 and 30 > 20,10 → True
    result = Peak().compute(
        _make_df([10, 15, 30, 20, 10, 5, 25]),
        column="close", kind="peak", order=2,
    )
    vals = list(result)
    assert vals[2] is True
    assert vals[0] is False
    assert vals[3] is False


def test_peak_edges_are_false():
    # Edges can't have enough neighbors → always False
    result = Peak().compute(_make_df([100, 50, 100]), column="close", kind="peak", order=1)
    assert list(result) == [False, False, False]


def test_peak_per_symbol():
    idx = pd.bdate_range("2024-01-01", periods=3)
    df_a = pd.DataFrame({"close": [10, 20, 10]}, index=idx)
    df_b = pd.DataFrame({"close": [20, 10, 20]}, index=idx)
    result_a = Peak().compute(df_a, column="close", kind="peak", order=1)
    result_b = Peak().compute(df_b, column="close", kind="peak", order=1)
    assert list(result_a) == [False, True, False]
    assert list(result_b) == [False, False, False]


def test_peak_has_name():
    assert Peak().name == "Peak"
