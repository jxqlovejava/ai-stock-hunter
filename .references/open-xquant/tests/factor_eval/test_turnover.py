"""Tests for compute_turnover metric."""

from __future__ import annotations

import pandas as pd
import pytest

from oxq.factor_eval.metrics import compute_turnover


def test_turnover_zero_when_ranks_stable():
    """If factor ranks don't change between periods, turnover = 0."""
    dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    symbols = ["A", "B", "C", "D"]

    factor = pd.DataFrame(
        [[1, 2, 3, 4], [10, 20, 30, 40], [100, 200, 300, 400]],
        index=dates, columns=symbols, dtype=float,
    )
    assert compute_turnover(factor) == pytest.approx(0.0)


def test_turnover_max_when_ranks_reverse():
    """If ranks completely reverse each period, turnover should be high."""
    dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    symbols = ["A", "B", "C", "D"]

    factor = pd.DataFrame(
        [[1, 2, 3, 4], [4, 3, 2, 1], [1, 2, 3, 4]],
        index=dates, columns=symbols, dtype=float,
    )
    result = compute_turnover(factor)
    assert result > 0.0


def test_turnover_hand_calculation():
    """Hand-calculate turnover for a simple case.

    Turnover per period = mean of |rank_change| / (N-1)

    Day 0: ranks [1,2,3] -> Day 1: ranks [1,3,2]
    Rank changes: [0, 1, 1], mean |change| = 2/3, normalized = (2/3)/(3-1) = 1/3

    Day 1: ranks [1,3,2] -> Day 2: ranks [3,1,2]
    Rank changes: [2, 2, 0], mean |change| = 4/3, normalized = (4/3)/(3-1) = 2/3

    Average turnover = (1/3 + 2/3) / 2 = 1/2 = 0.5
    """
    dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    symbols = ["A", "B", "C"]

    factor = pd.DataFrame(
        [[1, 2, 3], [1, 3, 2], [3, 1, 2]],
        index=dates, columns=symbols, dtype=float,
    )
    assert compute_turnover(factor) == pytest.approx(0.5, abs=1e-10)
