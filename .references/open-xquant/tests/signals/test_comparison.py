"""Tests for Comparison signal."""

import pandas as pd

from oxq.signals.comparison import Comparison


def _make_df() -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=5)
    return pd.DataFrame(
        {"sma_fast": [10, 20, 30, 25, 15], "sma_slow": [15, 15, 15, 15, 15]},
        index=idx,
    )


def test_comparison_gt():
    result = Comparison().compute(_make_df(), left="sma_fast", right="sma_slow", relationship="gt")
    assert list(result) == [False, True, True, True, False]


def test_comparison_lt():
    result = Comparison().compute(_make_df(), left="sma_fast", right="sma_slow", relationship="lt")
    assert list(result) == [True, False, False, False, False]


def test_comparison_eq():
    result = Comparison().compute(_make_df(), left="sma_fast", right="sma_slow", relationship="eq")
    assert list(result) == [False, False, False, False, True]


def test_comparison_ne():
    result = Comparison().compute(_make_df(), left="sma_fast", right="sma_slow", relationship="ne")
    assert list(result) == [True, True, True, True, False]


def test_comparison_per_symbol():
    idx = pd.bdate_range("2024-01-01", periods=2)
    df_a = pd.DataFrame({"x": [10, 20], "y": [15, 15]}, index=idx)
    df_b = pd.DataFrame({"x": [20, 10], "y": [15, 15]}, index=idx)
    result_a = Comparison().compute(df_a, left="x", right="y", relationship="gt")
    result_b = Comparison().compute(df_b, left="x", right="y", relationship="gt")
    assert list(result_a) == [False, True]
    assert list(result_b) == [True, False]


def test_comparison_has_name():
    assert Comparison().name == "Comparison"
