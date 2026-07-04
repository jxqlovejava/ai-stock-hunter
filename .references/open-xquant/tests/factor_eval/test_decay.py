"""Tests for compute_decay metric."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oxq.factor_eval.metrics import compute_decay


def test_decay_returns_ic_per_horizon():
    """Decay analysis returns IC at each forward horizon."""
    n = 50
    dates = pd.bdate_range("2024-01-01", periods=n)
    symbols = ["A", "B", "C", "D", "E"]

    np.random.seed(42)
    factor_vals = np.random.randn(n, len(symbols))
    base_prices = np.full((n, len(symbols)), 100.0)
    for t in range(1, n):
        base_prices[t] = base_prices[t - 1] * (1 + 0.01 * factor_vals[t - 1] + 0.005 * np.random.randn(len(symbols)))

    factor = pd.DataFrame(factor_vals, index=dates, columns=symbols)
    prices = pd.DataFrame(base_prices, index=dates, columns=symbols)

    result = compute_decay(factor, prices, horizons=[1, 5, 10])

    assert result["horizons"] == [1, 5, 10]
    assert len(result["ic_values"]) == 3
    # Short horizon should have stronger IC than long horizon
    assert abs(result["ic_values"][0]) > abs(result["ic_values"][2])


def test_decay_horizons_match_output():
    """Output horizons list matches input."""
    dates = pd.bdate_range("2024-01-01", periods=30)
    symbols = ["A", "B", "C", "D"]
    np.random.seed(0)

    factor = pd.DataFrame(
        np.random.randn(30, 4), index=dates, columns=symbols,
    )
    prices = pd.DataFrame(
        100 + np.cumsum(np.random.randn(30, 4) * 0.5, axis=0),
        index=dates, columns=symbols,
    )

    result = compute_decay(factor, prices, horizons=[1, 3, 7])
    assert result["horizons"] == [1, 3, 7]
    assert len(result["ic_values"]) == 3
    for v in result["ic_values"]:
        assert isinstance(v, float)
