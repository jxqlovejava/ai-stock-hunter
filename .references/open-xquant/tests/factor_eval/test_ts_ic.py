"""Tests for time-series IC (compute_ts_ic)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from oxq.factor_eval.metrics import compute_ts_ic


@pytest.fixture()
def trending_data():
    """3 symbols x 60 days. Symbol A has strong factor-return relationship,
    B has weak, C has none.

    For symbol A: factor = cumulative trend, returns follow factor direction.
    """
    n = 60
    dates = pd.bdate_range("2024-01-01", periods=n)
    np.random.seed(42)

    # Symbol A: factor predicts returns well
    factor_a = np.cumsum(np.random.randn(n) * 0.1)
    returns_a = 0.5 * factor_a + np.random.randn(n) * 0.1

    # Symbol B: weak relationship
    factor_b = np.cumsum(np.random.randn(n) * 0.1)
    returns_b = 0.1 * factor_b + np.random.randn(n) * 0.5

    # Symbol C: no relationship
    factor_c = np.cumsum(np.random.randn(n) * 0.1)
    returns_c = np.random.randn(n) * 0.5

    factor = pd.DataFrame(
        {"A": factor_a, "B": factor_b, "C": factor_c},
        index=dates,
    )
    fwd_returns = pd.DataFrame(
        {"A": returns_a, "B": returns_b, "C": returns_c},
        index=dates,
    )
    return factor, fwd_returns


def test_ts_ic_returns_per_symbol_and_mean(trending_data):
    """Should return per-symbol IC values and their mean."""
    factor, fwd_returns = trending_data
    result = compute_ts_ic(factor, fwd_returns)

    assert "mean" in result
    assert "per_symbol" in result
    assert len(result["per_symbol"]) == 3
    assert set(result["per_symbol"].keys()) == {"A", "B", "C"}


def test_ts_ic_hand_calculation(trending_data):
    """Mean should equal average of per-symbol Pearson correlations."""
    factor, fwd_returns = trending_data
    result = compute_ts_ic(factor, fwd_returns)

    # Hand-calculate per-symbol Pearson
    expected_per_symbol = {}
    for sym in ["A", "B", "C"]:
        f = factor[sym].dropna()
        r = fwd_returns[sym].dropna()
        common = f.index.intersection(r.index)
        corr, _ = stats.pearsonr(f.loc[common], r.loc[common])
        expected_per_symbol[sym] = corr

    expected_mean = np.mean(list(expected_per_symbol.values()))

    assert result["mean"] == pytest.approx(expected_mean, abs=1e-10)
    for sym in ["A", "B", "C"]:
        assert result["per_symbol"][sym] == pytest.approx(
            expected_per_symbol[sym], abs=1e-10
        )


def test_ts_ic_symbol_a_stronger_than_c(trending_data):
    """Symbol A (strong signal) should have higher abs(IC) than C (noise)."""
    factor, fwd_returns = trending_data
    result = compute_ts_ic(factor, fwd_returns)

    assert abs(result["per_symbol"]["A"]) > abs(result["per_symbol"]["C"])


def test_ts_ic_skips_symbols_with_few_observations():
    """Symbols with fewer than min_obs valid observations are skipped."""
    dates = pd.bdate_range("2024-01-01", periods=10)
    factor = pd.DataFrame(
        {"A": range(10), "B": [1, 2, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]},
        index=dates, dtype=float,
    )
    fwd_returns = pd.DataFrame(
        {"A": np.random.randn(10), "B": [0.1, 0.2, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]},
        index=dates, dtype=float,
    )

    result = compute_ts_ic(factor, fwd_returns, min_obs=5)
    # B has only 2 valid observations → skipped
    assert "A" in result["per_symbol"]
    assert "B" not in result["per_symbol"]


def test_ts_ic_single_symbol():
    """Should work with a single symbol — the key use case for rotation strategies."""
    n = 100
    dates = pd.bdate_range("2024-01-01", periods=n)
    np.random.seed(0)

    factor_vals = np.cumsum(np.random.randn(n) * 0.1)
    returns_vals = 0.3 * factor_vals + np.random.randn(n) * 0.2

    factor = pd.DataFrame({"ETF": factor_vals}, index=dates)
    fwd_returns = pd.DataFrame({"ETF": returns_vals}, index=dates)

    result = compute_ts_ic(factor, fwd_returns)
    assert len(result["per_symbol"]) == 1
    assert result["mean"] == result["per_symbol"]["ETF"]
    assert result["mean"] > 0  # positive relationship by construction
