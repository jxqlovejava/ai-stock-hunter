"""Tests for Crossover signal."""

import pandas as pd

from oxq.core.types import Signal
from oxq.signals.crossover import Crossover


def _make_df(
    fast_vals: list[float], slow_vals: list[float],
) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(fast_vals))
    return pd.DataFrame(
        {"close": fast_vals, "sma_10": fast_vals, "sma_50": slow_vals},
        index=dates,
    )


def test_crossover_satisfies_signal_protocol() -> None:
    assert isinstance(Crossover(), Signal)


def test_crossover_detects_cross_up() -> None:
    # Day 0: fast(8) <= slow(10)
    # Day 1: fast(9) <= slow(10)
    # Day 2: fast(11) > slow(10) → cross up!
    # Day 3: fast(12) > slow(10) → no cross (already above)
    df = _make_df(
        fast_vals=[8, 9, 11, 12],
        slow_vals=[10, 10, 10, 10],
    )
    result = Crossover().compute(df, fast="sma_10", slow="sma_50")
    assert isinstance(result, pd.Series)
    assert not result.iloc[1]   # no cross yet
    assert result.iloc[2]       # cross up here
    assert not result.iloc[3]   # already above, not a new cross


def test_crossover_no_signal_when_always_above() -> None:
    df = _make_df(
        fast_vals=[15, 16, 17],
        slow_vals=[10, 10, 10],
    )
    result = Crossover().compute(df, fast="sma_10", slow="sma_50")
    # First value is NaN due to shift; rest should be False
    assert not result.iloc[1]
    assert not result.iloc[2]


def test_crossover_per_symbol() -> None:
    dates = pd.bdate_range("2024-01-01", periods=3)
    df_aapl = pd.DataFrame(
        {"sma_10": [8, 9, 11], "sma_50": [10, 10, 10]}, index=dates,
    )
    df_msft = pd.DataFrame(
        {"sma_10": [12, 11, 9], "sma_50": [10, 10, 10]}, index=dates,
    )
    result_aapl = Crossover().compute(df_aapl, fast="sma_10", slow="sma_50")
    result_msft = Crossover().compute(df_msft, fast="sma_10", slow="sma_50")
    # AAPL crosses up on day 2
    assert result_aapl.iloc[2]
    # MSFT never crosses up (goes from above to below)
    assert not result_msft.iloc[1]
    assert not result_msft.iloc[2]


def test_crossover_has_name() -> None:
    assert Crossover().name == "Crossover"
