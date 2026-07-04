"""Tests for factor evaluation metrics — hand-calculated expected values."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from oxq.factor_eval.metrics import compute_ic, compute_rank_ic


@pytest.fixture()
def cross_section_data():
    """3 dates x 4 symbols with known factor-return correlation.

    Date 0: factor=[1,2,3,4], returns=[0.01,0.02,0.03,0.04] → perfect positive
    Date 1: factor=[4,3,2,1], returns=[0.01,0.02,0.03,0.04] → perfect negative
    Date 2: factor=[1,3,2,4], returns=[0.02,0.04,0.03,0.05] → strong positive
    """
    dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    symbols = ["A", "B", "C", "D"]

    factor = pd.DataFrame(
        [[1, 2, 3, 4], [4, 3, 2, 1], [1, 3, 2, 4]],
        index=dates, columns=symbols, dtype=float,
    )
    fwd_returns = pd.DataFrame(
        [[0.01, 0.02, 0.03, 0.04],
         [0.01, 0.02, 0.03, 0.04],
         [0.02, 0.04, 0.03, 0.05]],
        index=dates, columns=symbols, dtype=float,
    )
    return factor, fwd_returns


def test_ic_matches_hand_calculation(cross_section_data):
    """IC = mean of per-period Pearson(factor, forward_return)."""
    factor, fwd_returns = cross_section_data

    f2 = np.array([1.0, 3.0, 2.0, 4.0])
    r2 = np.array([0.02, 0.04, 0.03, 0.05])
    ic_date2 = stats.pearsonr(f2, r2)[0]

    expected_mean = (1.0 + (-1.0) + ic_date2) / 3

    result = compute_ic(factor, fwd_returns)
    assert result["mean"] == pytest.approx(expected_mean, abs=1e-10)
    assert len(result["series"]) == 3
    assert result["series"][0] == pytest.approx(1.0, abs=1e-10)
    assert result["series"][1] == pytest.approx(-1.0, abs=1e-10)


def test_ic_skips_periods_with_few_observations():
    """Periods with fewer than min_obs non-NaN values are skipped."""
    dates = pd.to_datetime(["2024-01-01", "2024-01-02"])
    symbols = ["A", "B", "C", "D"]

    factor = pd.DataFrame(
        [[1, 2, np.nan, np.nan], [1, 2, 3, 4]],
        index=dates, columns=symbols, dtype=float,
    )
    fwd_returns = pd.DataFrame(
        [[0.01, 0.02, np.nan, np.nan], [0.01, 0.02, 0.03, 0.04]],
        index=dates, columns=symbols, dtype=float,
    )

    result = compute_ic(factor, fwd_returns, min_obs=3)
    assert len(result["series"]) == 1
    assert result["mean"] == pytest.approx(1.0, abs=1e-10)


def test_ic_returns_nan_when_all_periods_skipped():
    """If all periods are skipped, mean should be NaN."""
    dates = pd.to_datetime(["2024-01-01"])
    symbols = ["A", "B"]

    factor = pd.DataFrame([[1, 2]], index=dates, columns=symbols, dtype=float)
    fwd_returns = pd.DataFrame([[0.01, 0.02]], index=dates, columns=symbols, dtype=float)

    result = compute_ic(factor, fwd_returns, min_obs=3)
    assert len(result["series"]) == 0
    assert np.isnan(result["mean"])


# ---------------------------------------------------------------------------
# compute_rank_ic
# ---------------------------------------------------------------------------

def test_rank_ic_uses_spearman(cross_section_data):
    """RankIC uses Spearman, not Pearson. Verify on the shared fixture."""
    factor, fwd_returns = cross_section_data

    f2 = np.array([1.0, 3.0, 2.0, 4.0])
    r2 = np.array([0.02, 0.04, 0.03, 0.05])
    rank_ic_date2 = stats.spearmanr(f2, r2)[0]

    expected_mean = (1.0 + (-1.0) + rank_ic_date2) / 3

    result = compute_rank_ic(factor, fwd_returns)
    assert result["mean"] == pytest.approx(expected_mean, abs=1e-10)


def test_rank_ic_differs_from_ic_on_nonlinear_data():
    """RankIC and IC should differ when relationship is monotonic but nonlinear."""
    dates = pd.to_datetime(["2024-01-01"])
    symbols = ["A", "B", "C", "D", "E"]

    factor = pd.DataFrame(
        [[1, 2, 3, 4, 5]], index=dates, columns=symbols, dtype=float,
    )
    fwd_returns = pd.DataFrame(
        [[0.01, 0.04, 0.09, 0.16, 0.25]], index=dates, columns=symbols, dtype=float,
    )

    ic_result = compute_ic(factor, fwd_returns)
    rank_ic_result = compute_rank_ic(factor, fwd_returns)

    assert rank_ic_result["mean"] == pytest.approx(1.0, abs=1e-10)
    assert ic_result["mean"] < 1.0
