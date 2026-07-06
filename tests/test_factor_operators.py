# -*- coding: utf-8 -*-
"""因子算子单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.base import rank, scale, ts_mean, ts_rank


@pytest.fixture
def wide_df():
    return pd.DataFrame(
        {
            "A": [1.0, 2.0, np.nan],
            "B": [3.0, 1.0, 4.0],
            "C": [2.0, np.nan, 1.0],
        },
        index=pd.date_range("2025-01-01", periods=3),
    )


def test_rank_shape_and_range(wide_df):
    r = rank(wide_df)
    assert r.shape == wide_df.shape
    # 每行非 NaN 值应在 (0,1]
    for i in range(len(wide_df)):
        row = r.iloc[i]
        valid = row.dropna()
        if len(valid) > 0:
            assert (valid >= 0).all() and (valid <= 1).all()


def test_rank_preserve_nan(wide_df):
    r = rank(wide_df)
    assert r.isna().equals(wide_df.isna())


def test_scale_sum_abs(wide_df):
    s = scale(wide_df, a=1.0)
    for i in range(len(wide_df)):
        row = s.iloc[i].dropna()
        if len(row) > 0:
            assert abs(row.abs().sum() - 1.0) < 1e-9


def test_ts_mean_rolling():
    df = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0]})
    out = ts_mean(df, n=2)
    expected = pd.DataFrame({"A": [1.0, 1.5, 2.5, 3.5]})
    pd.testing.assert_frame_equal(out, expected)


def test_ts_rank_shape():
    df = pd.DataFrame(
        {"A": [1.0, 2.0, 3.0], "B": [3.0, 2.0, 1.0]},
        index=pd.date_range("2025-01-01", periods=3),
    )
    out = ts_rank(df, n=2)
    assert out.shape == df.shape
    assert out.iloc[-1, 0] == 1.0
    assert out.iloc[-1, 1] == 0.5
