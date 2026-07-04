"""Tests for Timestamp signal."""

import pandas as pd

from oxq.signals.timestamp import Timestamp


def test_month_start():
    # 2024-01-02 (Tue) is first trading day of Jan
    # 2024-02-01 (Thu) is first trading day of Feb
    idx = pd.bdate_range("2024-01-02", "2024-02-15")
    df = pd.DataFrame({"close": range(len(idx))}, index=idx)
    result = Timestamp().compute(df, rule="month_start")
    assert result.iloc[0] == True   # Jan 2 — first bar
    feb1_idx = idx.get_loc(pd.Timestamp("2024-02-01"))
    assert result.iloc[feb1_idx] == True  # Feb 1 — month change
    assert result.iloc[1] == False         # Jan 3 — not month start


def test_month_end():
    idx = pd.bdate_range("2024-01-02", "2024-02-15")
    df = pd.DataFrame({"close": range(len(idx))}, index=idx)
    result = Timestamp().compute(df, rule="month_end")
    # 2024-01-31 (Wed) is last trading day of Jan
    jan31_idx = idx.get_loc(pd.Timestamp("2024-01-31"))
    assert result.iloc[jan31_idx] == True
    assert result.iloc[0] == False  # Jan 2 — not month end


def test_quarter_start():
    idx = pd.bdate_range("2024-03-01", "2024-04-15")
    df = pd.DataFrame({"close": range(len(idx))}, index=idx)
    result = Timestamp().compute(df, rule="quarter_start")
    # 2024-04-01 is first trading day of Q2
    apr1_idx = idx.get_loc(pd.Timestamp("2024-04-01"))
    assert result.iloc[apr1_idx] == True
    # Most days are not quarter start
    assert result.iloc[1] == False


def test_weekday():
    # weekday:0 = Monday
    idx = pd.bdate_range("2024-01-01", periods=10)
    df = pd.DataFrame({"close": range(10)}, index=idx)
    result = Timestamp().compute(df, rule="weekday:0")
    mondays = [idx[i].weekday() == 0 for i in range(len(idx))]
    assert list(result) == mondays


def test_unknown_rule_all_false():
    idx = pd.bdate_range("2024-01-01", periods=3)
    df = pd.DataFrame({"close": [1, 2, 3]}, index=idx)
    result = Timestamp().compute(df, rule="unknown_rule")
    assert list(result) == [False, False, False]


def test_timestamp_per_symbol():
    idx = pd.bdate_range("2024-01-01", periods=5)
    df_a = pd.DataFrame({"close": range(5)}, index=idx)
    df_b = pd.DataFrame({"close": range(5)}, index=idx)
    result_a = Timestamp().compute(df_a, rule="weekday:0")
    result_b = Timestamp().compute(df_b, rule="weekday:0")
    assert list(result_a) == list(result_b)


def test_timestamp_has_name():
    assert Timestamp().name == "Timestamp"
