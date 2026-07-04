"""Tests for RunResult performance metrics."""

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Portfolio
from oxq.portfolio.analytics import RunResult


def _make_result(values: list[float]) -> RunResult:
    """Build a RunResult from a sequence of portfolio values."""
    dates = pd.bdate_range("2024-01-01", periods=len(values))
    equity_curve = [(d, v) for d, v in zip(dates, values)]
    return RunResult(
        portfolio=Portfolio(cash=Decimal(str(values[-1])) if values else Decimal("0")),
        trades=[],
        equity_curve=equity_curve,
        mktdata={},
    )


# -- annualized_return --------------------------------------------------------

def test_annualized_return_basic() -> None:
    values = np.linspace(100, 110, 252).tolist()
    result = _make_result(values)
    # CAGR: (V_final / V_initial) ^ (252 / N) - 1
    n = len(values) - 1  # 251 daily returns
    expected = (110 / 100) ** (252 / n) - 1
    assert result.annualized_return() == pytest.approx(expected, rel=1e-4)


def test_annualized_return_empty() -> None:
    result = _make_result([])
    assert result.annualized_return() == 0.0


def test_annualized_return_single_point() -> None:
    result = _make_result([100.0])
    assert result.annualized_return() == 0.0


# -- annualized_volatility ----------------------------------------------------

def test_annualized_volatility_basic() -> None:
    values = [100.0, 102.0, 99.0, 103.0, 101.0, 104.0]
    result = _make_result(values)
    arr = np.array(values)
    log_ret = np.diff(np.log(arr))
    expected = float(np.std(log_ret, ddof=1) * np.sqrt(252))
    assert result.annualized_volatility() == pytest.approx(expected, rel=1e-6)


def test_annualized_volatility_empty() -> None:
    result = _make_result([])
    assert result.annualized_volatility() == 0.0


def test_annualized_volatility_constant() -> None:
    result = _make_result([100.0] * 10)
    assert result.annualized_volatility() == 0.0


# -- calmar_ratio --------------------------------------------------------------

def test_calmar_ratio_basic() -> None:
    values = [100.0, 110.0, 105.0, 115.0, 120.0]
    result = _make_result(values)
    ann_ret = result.annualized_return()
    mdd = result.max_drawdown()
    expected = ann_ret / abs(mdd)
    assert result.calmar_ratio() == pytest.approx(expected, rel=1e-6)


def test_calmar_ratio_no_drawdown() -> None:
    result = _make_result([100.0, 110.0, 120.0, 130.0])
    assert result.calmar_ratio() == 0.0


def test_calmar_ratio_empty() -> None:
    result = _make_result([])
    assert result.calmar_ratio() == 0.0


# -- sortino_ratio -------------------------------------------------------------

def test_sortino_ratio_basic() -> None:
    values = [100.0, 102.0, 99.0, 103.0, 97.0, 105.0]
    result = _make_result(values)
    arr = np.array(values)
    log_ret = np.diff(np.log(arr))
    downside = log_ret[log_ret < 0]
    downside_dev = float(np.sqrt(np.mean(downside**2)) * np.sqrt(252))
    ann_ret = float(np.mean(log_ret) * 252)
    expected = ann_ret / downside_dev
    assert result.sortino_ratio() == pytest.approx(expected, rel=1e-4)


def test_sortino_ratio_no_downside() -> None:
    result = _make_result([100.0, 110.0, 120.0, 130.0])
    assert result.sortino_ratio() == 0.0


def test_sortino_ratio_empty() -> None:
    result = _make_result([])
    assert result.sortino_ratio() == 0.0


# -- total_return --------------------------------------------------------------

def test_total_return_positive() -> None:
    result = _make_result([100, 110, 115])
    assert result.total_return() == pytest.approx(0.15, rel=1e-4)


def test_total_return_negative() -> None:
    result = _make_result([100, 90, 85])
    assert result.total_return() == pytest.approx(-0.15, rel=1e-4)


def test_total_return_empty() -> None:
    result = _make_result([])
    assert result.total_return() == 0.0


def test_total_return_single_point() -> None:
    result = _make_result([100.0])
    assert result.total_return() == 0.0


def test_total_return_zero_start() -> None:
    result = _make_result([0.0, 100.0])
    assert result.total_return() == 0.0


# -- sharpe_ratio --------------------------------------------------------------

def test_sharpe_ratio_basic() -> None:
    values = [100, 102, 99, 103, 101, 104]
    result = _make_result(values)
    arr = np.array(values, dtype=float)
    returns = np.diff(arr) / arr[:-1]
    expected = float(np.mean(returns) / np.std(returns) * np.sqrt(252))
    assert result.sharpe_ratio() == pytest.approx(expected, rel=1e-4)


def test_sharpe_ratio_empty() -> None:
    result = _make_result([])
    assert result.sharpe_ratio() == 0.0


def test_sharpe_ratio_constant() -> None:
    result = _make_result([100.0] * 10)
    assert result.sharpe_ratio() == 0.0


def test_sharpe_ratio_single_point() -> None:
    result = _make_result([100.0])
    assert result.sharpe_ratio() == 0.0


# -- max_drawdown --------------------------------------------------------------

def test_max_drawdown_basic() -> None:
    values = [100, 110, 90, 95, 85]
    result = _make_result(values)
    arr = np.array(values, dtype=float)
    peak = np.maximum.accumulate(arr)
    expected = float(np.min((arr - peak) / peak))
    assert result.max_drawdown() == pytest.approx(expected, rel=1e-4)


def test_max_drawdown_no_drawdown() -> None:
    result = _make_result([100, 110, 120, 130])
    assert result.max_drawdown() == 0.0


def test_max_drawdown_empty() -> None:
    result = _make_result([])
    assert result.max_drawdown() == 0.0


def test_max_drawdown_single_point() -> None:
    result = _make_result([100.0])
    assert result.max_drawdown() == 0.0


def test_max_drawdown_returns_negative() -> None:
    values = [100, 110, 90, 95, 85]
    result = _make_result(values)
    assert result.max_drawdown() <= 0


# -- daily_returns -------------------------------------------------------------

def test_daily_returns_basic() -> None:
    values = [100.0, 105.0, 102.0, 110.0]
    result = _make_result(values)
    dr = result.daily_returns()
    assert isinstance(dr, pd.Series)
    assert len(dr) == 3  # one fewer than values
    # hand-calculated: 5/100, -3/105, 8/102
    assert dr.iloc[0] == pytest.approx(0.05, rel=1e-6)
    assert dr.iloc[1] == pytest.approx(-3.0 / 105.0, rel=1e-6)
    assert dr.iloc[2] == pytest.approx(8.0 / 102.0, rel=1e-6)


def test_daily_returns_preserves_date_index() -> None:
    values = [100.0, 110.0, 105.0]
    result = _make_result(values)
    dr = result.daily_returns()
    dates = [d for d, _ in result.equity_curve]
    # index should be dates[1:] (return on each day relative to previous)
    assert list(dr.index) == dates[1:]


def test_daily_returns_empty() -> None:
    result = _make_result([])
    dr = result.daily_returns()
    assert isinstance(dr, pd.Series)
    assert len(dr) == 0


def test_daily_returns_single_point() -> None:
    result = _make_result([100.0])
    dr = result.daily_returns()
    assert len(dr) == 0


# -- monthly_returns -----------------------------------------------------------

def _make_result_monthly(
    start: str, periods: int, values: list[float],
) -> RunResult:
    """Build a RunResult with explicit business-day dates for monthly tests."""
    dates = pd.bdate_range(start, periods=periods)
    equity_curve = [(d, v) for d, v in zip(dates, values)]
    return RunResult(
        portfolio=Portfolio(cash=Decimal(str(values[-1]))),
        trades=[],
        equity_curve=equity_curve,
        mktdata={},
    )


def test_monthly_returns_basic() -> None:
    # Jan: 22 business days, Feb: 19 business days  (2024)
    # Use 3 months of data to get 2 full monthly returns
    dates = pd.bdate_range("2024-01-02", "2024-03-29")
    n = len(dates)
    # Linear growth from 100 to 200
    values = np.linspace(100, 200, n).tolist()
    result = RunResult(
        portfolio=Portfolio(cash=Decimal("200")),
        trades=[],
        equity_curve=[(d, v) for d, v in zip(dates, values)],
        mktdata={},
    )
    mr = result.monthly_returns()
    assert isinstance(mr, pd.Series)
    # Should have one entry per month
    assert len(mr) >= 2
    # Each monthly return should be positive (linear growth)
    assert (mr > 0).all()


def test_monthly_returns_uses_last_day_of_month() -> None:
    # 2024-01-02 to 2024-02-29: two months
    dates = pd.bdate_range("2024-01-02", "2024-02-29")
    n = len(dates)
    values = [100.0] * n
    # Make Jan end at 110 and Feb end at 99
    jan_last_idx = None
    for i, d in enumerate(dates):
        if d.month == 1:
            jan_last_idx = i
    values[jan_last_idx] = 110.0  # type: ignore[index]
    # Feb last day = last element
    values[-1] = 99.0
    result = RunResult(
        portfolio=Portfolio(cash=Decimal("99")),
        trades=[],
        equity_curve=[(d, v) for d, v in zip(dates, values)],
        mktdata={},
    )
    mr = result.monthly_returns()
    # Jan return: (110 - 100) / 100 = 0.10
    assert mr.iloc[0] == pytest.approx(0.10, rel=1e-6)
    # Feb return: (99 - 110) / 110
    assert mr.iloc[1] == pytest.approx((99.0 - 110.0) / 110.0, rel=1e-6)


def test_monthly_returns_empty() -> None:
    result = _make_result([])
    mr = result.monthly_returns()
    assert isinstance(mr, pd.Series)
    assert len(mr) == 0


# -- drawdown_series -----------------------------------------------------------

def test_drawdown_series_basic() -> None:
    values = [100.0, 110.0, 90.0, 95.0, 85.0]
    result = _make_result(values)
    dd = result.drawdown_series()
    assert isinstance(dd, pd.Series)
    assert len(dd) == 5
    # hand-calculated:
    # peak: 100, 110, 110, 110, 110
    # dd:   0,   0,   (90-110)/110, (95-110)/110, (85-110)/110
    assert dd.iloc[0] == pytest.approx(0.0)
    assert dd.iloc[1] == pytest.approx(0.0)
    assert dd.iloc[2] == pytest.approx(-20.0 / 110.0, rel=1e-6)
    assert dd.iloc[3] == pytest.approx(-15.0 / 110.0, rel=1e-6)
    assert dd.iloc[4] == pytest.approx(-25.0 / 110.0, rel=1e-6)


def test_drawdown_series_preserves_date_index() -> None:
    values = [100.0, 110.0, 90.0]
    result = _make_result(values)
    dd = result.drawdown_series()
    dates = [d for d, _ in result.equity_curve]
    assert list(dd.index) == dates


def test_drawdown_series_no_drawdown() -> None:
    values = [100.0, 110.0, 120.0, 130.0]
    result = _make_result(values)
    dd = result.drawdown_series()
    assert (dd == 0.0).all()


def test_drawdown_series_empty() -> None:
    result = _make_result([])
    dd = result.drawdown_series()
    assert isinstance(dd, pd.Series)
    assert len(dd) == 0


def test_drawdown_series_single_point() -> None:
    result = _make_result([100.0])
    dd = result.drawdown_series()
    assert len(dd) == 1
    assert dd.iloc[0] == 0.0


# -- benchmark_prices ----------------------------------------------------------

def test_run_result_benchmark_prices_default_empty() -> None:
    """RunResult.benchmark_prices defaults to empty dict."""
    result = _make_result([100.0, 110.0])
    assert result.benchmark_prices == {}


def test_run_result_benchmark_prices_stored() -> None:
    """RunResult stores benchmark price series."""
    dates = pd.bdate_range("2024-01-01", periods=3)
    bench = pd.Series([100.0, 101.0, 102.0], index=dates)
    result = RunResult(
        portfolio=Portfolio(cash=Decimal("100")),
        trades=[],
        equity_curve=[(d, v) for d, v in zip(dates, [100, 110, 120])],
        mktdata={},
        benchmark_prices={"510300.SS": bench},
    )
    assert "510300.SS" in result.benchmark_prices
    assert len(result.benchmark_prices["510300.SS"]) == 3


def test_drawdown_series_min_equals_max_drawdown() -> None:
    """drawdown_series().min() should equal max_drawdown()."""
    values = [100.0, 110.0, 90.0, 95.0, 85.0, 120.0]
    result = _make_result(values)
    assert result.drawdown_series().min() == pytest.approx(
        result.max_drawdown(), rel=1e-6,
    )


# -- snapshots / DataFrame methods --------------------------------------------

from oxq.core.types import BarSnapshot, PositionSnapshot


def _make_result_with_snapshots() -> RunResult:
    """Build a RunResult with snapshots for testing DataFrame methods."""
    dates = pd.bdate_range("2024-01-01", periods=3)
    snapshots = [
        BarSnapshot(
            date=dates[0],
            target_weights={"AAPL": 0.6, "GOOG": 0.4},
            adjusted_weights={"AAPL": 0.5, "GOOG": 0.3, "CASH": 0.2},
            positions={"AAPL": PositionSnapshot(shares=100, avg_cost=150.0)},
            cash=85000.0,
            total_value=100000.0,
        ),
        BarSnapshot(
            date=dates[1],
            target_weights={"AAPL": 0.5, "GOOG": 0.5},
            adjusted_weights={"AAPL": 0.5, "GOOG": 0.5},
            positions={
                "AAPL": PositionSnapshot(shares=100, avg_cost=150.0),
                "GOOG": PositionSnapshot(shares=50, avg_cost=120.0),
            },
            cash=69000.0,
            total_value=100500.0,
        ),
        BarSnapshot(
            date=dates[2],
            target_weights={"AAPL": 0.7, "GOOG": 0.3},
            adjusted_weights={"AAPL": 0.7, "GOOG": 0.3},
            positions={
                "AAPL": PositionSnapshot(shares=140, avg_cost=152.0),
                "GOOG": PositionSnapshot(shares=30, avg_cost=120.0),
            },
            cash=45000.0,
            total_value=101000.0,
        ),
    ]
    return RunResult(
        portfolio=Portfolio(cash=Decimal("45000")),
        trades=[],
        equity_curve=[(s.date, s.total_value) for s in snapshots],
        mktdata={},
        snapshots=snapshots,
    )


def test_weights_df() -> None:
    result = _make_result_with_snapshots()
    df = result.weights_df()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3
    assert "AAPL" in df.columns
    assert "GOOG" in df.columns
    # First row: target_weights
    assert df.iloc[0]["AAPL"] == 0.6
    assert df.iloc[0]["GOOG"] == 0.4
    # NaN filled with 0.0
    assert df.fillna(0).iloc[0].sum() == pytest.approx(1.0)


def test_adj_weights_df() -> None:
    result = _make_result_with_snapshots()
    df = result.adj_weights_df()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3
    # First row: adjusted_weights includes CASH
    assert df.iloc[0]["AAPL"] == 0.5
    assert df.iloc[0]["GOOG"] == 0.3
    assert df.iloc[0]["CASH"] == 0.2


def test_positions_df() -> None:
    result = _make_result_with_snapshots()
    df = result.positions_df()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3
    # First bar: only AAPL
    assert df.iloc[0]["AAPL"] == 100
    assert df.fillna(0).iloc[0]["GOOG"] == 0
    # Second bar: AAPL + GOOG
    assert df.iloc[1]["AAPL"] == 100
    assert df.iloc[1]["GOOG"] == 50


def test_weights_df_empty_snapshots() -> None:
    result = _make_result([100.0, 110.0])
    df = result.weights_df()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0


def test_positions_df_empty_snapshots() -> None:
    result = _make_result([100.0, 110.0])
    df = result.positions_df()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0
