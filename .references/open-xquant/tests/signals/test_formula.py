"""Tests for Formula signal."""

import pandas as pd

from oxq.signals.formula import Formula


def _make_df() -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=4)
    return pd.DataFrame(
        {"sma_fast": [10, 20, 30, 25], "sma_slow": [15, 15, 15, 15], "rsi": [40, 70, 80, 30]},
        index=idx,
    )


def test_formula_simple():
    result = Formula().compute(_make_df(), expr="sma_fast > sma_slow")
    assert list(result) == [False, True, True, True]


def test_formula_compound_and():
    result = Formula().compute(_make_df(), expr="sma_fast > sma_slow and rsi > 50")
    assert list(result) == [False, True, True, False]


def test_formula_compound_or():
    result = Formula().compute(_make_df(), expr="sma_fast < 15 or rsi > 75")
    assert list(result) == [True, False, True, False]


def test_formula_per_symbol():
    idx = pd.bdate_range("2024-01-01", periods=2)
    df_a = pd.DataFrame({"x": [10, 20], "y": [15, 15]}, index=idx)
    df_b = pd.DataFrame({"x": [20, 10], "y": [15, 15]}, index=idx)
    result_a = Formula().compute(df_a, expr="x > y")
    result_b = Formula().compute(df_b, expr="x > y")
    assert list(result_a) == [False, True]
    assert list(result_b) == [True, False]


def test_formula_has_name():
    assert Formula().name == "Formula"
