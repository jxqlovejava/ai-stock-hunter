"""Tests for WalkForward — rolling and anchored walk-forward analysis."""

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from oxq.core.strategy import Strategy
from oxq.core.types import Portfolio
from oxq.indicators.sma import SMA
from oxq.optimize.paramset import ParameterSet
from oxq.optimize.walk_forward import (
    WalkForward,
    WalkForwardResult,
    WindowResult,
    _parse_period,
)
from oxq.portfolio.analytics import RunResult
from oxq.portfolio.optimizers import EqualWeightOptimizer
from oxq.signals.crossover import Crossover
from oxq.trade.sim_broker import SimBroker
from oxq.universe.static import StaticUniverse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeMarketDataProvider:
    """In-memory market data provider for testing."""

    def __init__(self, data: dict[str, pd.DataFrame]) -> None:
        self._data = data

    def get_bars(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        df = self._data[symbol]
        return df[(df.index >= pd.Timestamp(start, tz="UTC")) & (df.index <= pd.Timestamp(end, tz="UTC"))]

    def get_latest(self, symbol: str) -> pd.Series:
        return self._data[symbol].iloc[-1]


def _make_result(values: list[float]) -> RunResult:
    dates = pd.bdate_range("2024-01-01", periods=len(values))
    equity_curve = [(d, v) for d, v in zip(dates, values)]
    return RunResult(
        portfolio=Portfolio(cash=Decimal(str(values[-1])) if values else Decimal("0")),
        trades=[],
        equity_curve=equity_curve,
        mktdata={},
    )


def _make_long_data(start: str, end: str) -> dict[str, pd.DataFrame]:
    """Create market data spanning the given date range.

    Trending pattern: up -> down -> up cycle to ensure SMA crossovers.
    """
    dates = pd.bdate_range(start, end, tz="UTC")
    n = len(dates)
    # Create a sine-like pattern on top of an uptrend
    t = np.arange(n, dtype=float)
    closes = 100.0 + 0.1 * t + 20.0 * np.sin(2 * np.pi * t / 120)
    closes = closes.tolist()
    return {
        "AAPL": pd.DataFrame(
            {
                "open": closes,
                "high": [c + 1 for c in closes],
                "low": [c - 1 for c in closes],
                "close": closes,
                "volume": [1_000_000] * n,
            },
            index=dates,
        ),
    }


def _make_crossover_signal():
    """Create a Crossover signal with required_indicators."""
    signal = Crossover()
    signal.required_indicators = {
        "sma_fast": (SMA(), {"period": 10}),
        "sma_slow": (SMA(), {"period": 30}),
    }
    return signal


def _make_strategy() -> Strategy:
    return Strategy(
        name="test_sma",
        hypothesis="SMA crossover",
        universe=StaticUniverse(("AAPL",)),
        signals={
            "sma_cross": (_make_crossover_signal(), {"fast": "sma_fast", "slow": "sma_slow"}),
        },
        portfolio=EqualWeightOptimizer(),
    )


# ---------------------------------------------------------------------------
# _parse_period
# ---------------------------------------------------------------------------


def test_parse_period_years() -> None:
    offset = _parse_period("2Y")
    assert offset == pd.DateOffset(years=2)


def test_parse_period_months() -> None:
    offset = _parse_period("6M")
    assert offset == pd.DateOffset(months=6)


def test_parse_period_days() -> None:
    offset = _parse_period("63D")
    assert offset == pd.DateOffset(days=63)


def test_parse_period_lowercase() -> None:
    offset = _parse_period("3m")
    assert offset == pd.DateOffset(months=3)


def test_parse_period_whitespace() -> None:
    offset = _parse_period("  2 Y  ")
    assert offset == pd.DateOffset(years=2)


def test_parse_period_invalid_format() -> None:
    with pytest.raises(ValueError, match="Invalid period"):
        _parse_period("2W")


def test_parse_period_empty() -> None:
    with pytest.raises(ValueError, match="Invalid period"):
        _parse_period("")


def test_parse_period_no_number() -> None:
    with pytest.raises(ValueError, match="Invalid period"):
        _parse_period("Y")


# ---------------------------------------------------------------------------
# _generate_windows — rolling
# ---------------------------------------------------------------------------


def test_rolling_windows_basic() -> None:
    """Rolling windows slide forward by test_period (default step)."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(ps, train_period="1Y", test_period="6M")
    windows = wf._generate_windows("2020-01-01", "2024-12-31")

    assert len(windows) > 0
    for train_start, train_end, test_start, test_end in windows:
        # test_start = train_end + 1 day
        ts = pd.Timestamp(test_start)
        te_plus1 = pd.Timestamp(train_end) + pd.DateOffset(days=1)
        assert ts == te_plus1


def test_rolling_windows_non_overlapping_tests() -> None:
    """With default step = test_period, test periods don't overlap."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(ps, train_period="1Y", test_period="6M")
    windows = wf._generate_windows("2020-01-01", "2024-12-31")

    for i in range(1, len(windows)):
        prev_test_end = pd.Timestamp(windows[i - 1][3])
        curr_test_start = pd.Timestamp(windows[i][2])
        assert curr_test_start > prev_test_end


def test_rolling_window_train_size_constant() -> None:
    """Rolling mode: all train windows have similar size (+-1 day)."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(ps, train_period="1Y", test_period="6M")
    windows = wf._generate_windows("2020-01-01", "2024-12-31")

    train_days = []
    for ts, te, _, _ in windows:
        days = (pd.Timestamp(te) - pd.Timestamp(ts)).days
        train_days.append(days)

    # All train periods should be approximately 365 days
    for d in train_days:
        assert 363 <= d <= 366


# ---------------------------------------------------------------------------
# _generate_windows — anchored
# ---------------------------------------------------------------------------


def test_anchored_windows_train_starts_at_start() -> None:
    """Anchored mode: train_start is always the overall start date."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(ps, train_period="1Y", test_period="6M", anchored=True)
    windows = wf._generate_windows("2018-01-01", "2024-12-31")

    assert len(windows) > 0
    for train_start, _, _, _ in windows:
        assert train_start == "2018-01-01"


def test_anchored_windows_train_grows() -> None:
    """Anchored mode: train_end moves forward each window."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(ps, train_period="2Y", test_period="6M", anchored=True)
    windows = wf._generate_windows("2018-01-01", "2024-12-31")

    assert len(windows) >= 2
    for i in range(1, len(windows)):
        prev_te = pd.Timestamp(windows[i - 1][1])
        curr_te = pd.Timestamp(windows[i][1])
        assert curr_te > prev_te


def test_anchored_no_infinite_loop() -> None:
    """Regression: anchored mode must not loop infinitely.

    The original bug was that cursor wasn't advancing because
    train_start was always reset to start_dt, making step ineffective.
    """
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(ps, train_period="2Y", test_period="6M", anchored=True)
    # If this hangs, the bug is back
    windows = wf._generate_windows("2018-01-01", "2024-12-31")
    assert len(windows) == 10  # Expected: 10 windows


# ---------------------------------------------------------------------------
# _generate_windows — custom step
# ---------------------------------------------------------------------------


def test_custom_step() -> None:
    """Custom step controls how much the window slides forward."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(
        ps, train_period="1Y", test_period="6M", step="3M",
    )
    windows = wf._generate_windows("2020-01-01", "2024-12-31")

    # With 3M step, windows overlap more
    assert len(windows) > 0

    # Consecutive test_starts should be ~3 months apart
    for i in range(1, min(3, len(windows))):
        diff = pd.Timestamp(windows[i][2]) - pd.Timestamp(windows[i - 1][2])
        # ~90 days, but DateOffset(months=3) varies
        assert 85 <= diff.days <= 95


# ---------------------------------------------------------------------------
# _generate_windows — edge cases
# ---------------------------------------------------------------------------


def test_windows_clips_test_end_to_data_range() -> None:
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(ps, train_period="1Y", test_period="1Y")
    # Only room for train + partial test
    windows = wf._generate_windows("2020-01-01", "2021-06-30")

    if windows:
        last_test_end = pd.Timestamp(windows[-1][3])
        assert last_test_end <= pd.Timestamp("2021-06-30")


def test_windows_empty_if_range_too_short() -> None:
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(ps, train_period="2Y", test_period="1Y")
    # Range is only 1Y — not enough for train + test
    windows = wf._generate_windows("2020-01-01", "2020-12-31")
    assert windows == []


# ---------------------------------------------------------------------------
# WalkForwardResult — stitched metrics
# ---------------------------------------------------------------------------


def _make_window_result(
    values: list[float],
    in_sample_metric: float = 0.5,
) -> WindowResult:
    return WindowResult(
        train_start="2020-01-01",
        train_end="2021-12-31",
        test_start="2022-01-01",
        test_end="2022-12-31",
        best_params={"sma": {"period": 10}},
        in_sample_metric=in_sample_metric,
        oos_result=_make_result(values),
    )


def test_oos_equity_curve_stitched() -> None:
    w1 = _make_window_result([100, 105, 110])
    w2 = _make_window_result([110, 115, 120])
    wfr = WalkForwardResult(
        windows=[w1, w2], metric="sharpe_ratio", metric_direction="maximize",
    )
    curve = wfr.oos_equity_curve
    assert len(curve) == 6  # 3 + 3


def test_oos_total_return() -> None:
    w1 = _make_window_result([100, 110])
    w2 = _make_window_result([110, 121])
    wfr = WalkForwardResult(
        windows=[w1, w2], metric="sharpe_ratio", metric_direction="maximize",
    )
    # Stitched: [100, 110, 110, 121]
    # Total return: (121 - 100) / 100 = 0.21
    assert wfr.oos_total_return() == pytest.approx(0.21, rel=1e-4)


def test_oos_total_return_empty() -> None:
    wfr = WalkForwardResult(
        windows=[], metric="sharpe_ratio", metric_direction="maximize",
    )
    assert wfr.oos_total_return() == 0.0


def test_oos_sharpe_ratio() -> None:
    values = [100, 102, 99, 103, 101, 104]
    w = _make_window_result(values)
    wfr = WalkForwardResult(
        windows=[w], metric="sharpe_ratio", metric_direction="maximize",
    )
    # Hand-calculate: simple returns, then sharpe
    arr = np.array(values, dtype=float)
    returns = np.diff(arr) / arr[:-1]
    expected = float(np.mean(returns) / np.std(returns) * np.sqrt(252))
    assert wfr.oos_sharpe_ratio() == pytest.approx(expected, rel=1e-4)


def test_oos_sharpe_ratio_empty() -> None:
    wfr = WalkForwardResult(
        windows=[], metric="sharpe_ratio", metric_direction="maximize",
    )
    assert wfr.oos_sharpe_ratio() == 0.0


def test_oos_max_drawdown() -> None:
    values = [100, 110, 90, 95, 85]
    w = _make_window_result(values)
    wfr = WalkForwardResult(
        windows=[w], metric="sharpe_ratio", metric_direction="maximize",
    )
    # peak: 100, 110, 110, 110, 110
    # dd: (85 - 110) / 110 = -0.2272...
    arr = np.array(values, dtype=float)
    peak = np.maximum.accumulate(arr)
    expected = float(np.min((arr - peak) / peak))
    assert wfr.oos_max_drawdown() == pytest.approx(expected, rel=1e-4)


def test_oos_max_drawdown_empty() -> None:
    wfr = WalkForwardResult(
        windows=[], metric="sharpe_ratio", metric_direction="maximize",
    )
    assert wfr.oos_max_drawdown() == 0.0


# ---------------------------------------------------------------------------
# WalkForwardResult — deterioration
# ---------------------------------------------------------------------------


def test_deterioration_basic() -> None:
    """Deterioration = (mean_oos - mean_is) / |mean_is| for the optimized metric."""
    # IS metric = 1.0, OOS sharpe will be computed from equity values
    w = _make_window_result([100, 110, 120], in_sample_metric=1.0)
    wfr = WalkForwardResult(
        windows=[w], metric="sharpe_ratio", metric_direction="maximize",
    )
    det = wfr.deterioration()
    if "sharpe_ratio" in det:
        oos_sharpe = w.oos_result.sharpe_ratio()
        expected = (oos_sharpe - 1.0) / abs(1.0)
        assert det["sharpe_ratio"] == pytest.approx(expected, rel=1e-4)


def test_deterioration_empty_windows() -> None:
    wfr = WalkForwardResult(
        windows=[], metric="sharpe_ratio", metric_direction="maximize",
    )
    assert wfr.deterioration() == {}


# ---------------------------------------------------------------------------
# WalkForwardResult — to_dataframe
# ---------------------------------------------------------------------------


def test_to_dataframe() -> None:
    w = _make_window_result([100, 105, 110], in_sample_metric=0.8)
    wfr = WalkForwardResult(
        windows=[w], metric="sharpe_ratio", metric_direction="maximize",
    )
    df = wfr.to_dataframe()
    assert len(df) == 1
    assert "train_start" in df.columns
    assert "test_end" in df.columns
    assert "in_sample_metric" in df.columns
    assert "sma.period" in df.columns
    assert "oos_total_return" in df.columns
    assert "oos_sharpe_ratio" in df.columns
    assert "oos_num_trades" in df.columns
    assert df["in_sample_metric"].iloc[0] == 0.8


# ---------------------------------------------------------------------------
# WalkForward.run — integration
# ---------------------------------------------------------------------------


def test_walk_forward_run_rolling() -> None:
    """WalkForward.run produces correct number of windows in rolling mode."""
    data = _make_long_data("2018-01-01", "2022-12-31")
    market = FakeMarketDataProvider(data)

    ps = ParameterSet("test")
    ps.add("sma_cross", "fast", values=["sma_fast"])

    wf = WalkForward(ps, train_period="2Y", test_period="1Y")
    result = wf.run(
        strategy=_make_strategy(),
        market=market,
        broker_factory=SimBroker,
        start="2018-01-01",
        end="2022-12-31",
        metric="sharpe_ratio",
    )

    assert len(result.windows) > 0
    assert result.metric == "sharpe_ratio"
    assert result.metric_direction == "maximize"

    # Each window has valid params and an OOS RunResult
    for w in result.windows:
        assert isinstance(w.best_params, dict)
        assert isinstance(w.oos_result, RunResult)
        assert len(w.oos_result.equity_curve) > 0


def test_walk_forward_run_empty_range() -> None:
    """WalkForward.run returns empty result if range is too short."""
    data = _make_long_data("2020-01-01", "2020-06-30")
    market = FakeMarketDataProvider(data)

    ps = ParameterSet("test")
    ps.add("sma_cross", "fast", values=["sma_fast"])

    wf = WalkForward(ps, train_period="2Y", test_period="1Y")
    result = wf.run(
        strategy=_make_strategy(),
        market=market,
        broker_factory=SimBroker,
        start="2020-01-01",
        end="2020-06-30",
        metric="sharpe_ratio",
    )

    assert len(result.windows) == 0


# ---------------------------------------------------------------------------
# WalkForwardResult — stitched metrics (multi-window)
# ---------------------------------------------------------------------------


def test_oos_sharpe_ratio_multi_window() -> None:
    """Stitched sharpe across multiple windows uses combined equity curve."""
    w1 = _make_window_result([100, 105, 110])
    w2 = _make_window_result([110, 108, 115])
    wfr = WalkForwardResult(
        windows=[w1, w2], metric="sharpe_ratio", metric_direction="maximize",
    )
    # Stitched: [100, 105, 110, 110, 108, 115]
    combined = np.array([100, 105, 110, 110, 108, 115], dtype=float)
    returns = np.diff(combined) / combined[:-1]
    expected = float(np.mean(returns) / np.std(returns) * np.sqrt(252))
    assert wfr.oos_sharpe_ratio() == pytest.approx(expected, rel=1e-4)


def test_oos_max_drawdown_multi_window() -> None:
    """Max drawdown spans across window boundaries."""
    # Window 1 peaks at 120, Window 2 drops to 90
    w1 = _make_window_result([100, 120])
    w2 = _make_window_result([115, 90])
    wfr = WalkForwardResult(
        windows=[w1, w2], metric="sharpe_ratio", metric_direction="maximize",
    )
    combined = np.array([100, 120, 115, 90], dtype=float)
    peak = np.maximum.accumulate(combined)
    expected = float(np.min((combined - peak) / peak))
    assert wfr.oos_max_drawdown() == pytest.approx(expected, rel=1e-4)


def test_oos_total_return_zero_start() -> None:
    w = _make_window_result([0.0, 100.0])
    wfr = WalkForwardResult(
        windows=[w], metric="sharpe_ratio", metric_direction="maximize",
    )
    assert wfr.oos_total_return() == 0.0


def test_oos_sharpe_ratio_constant_values() -> None:
    w = _make_window_result([100.0, 100.0, 100.0])
    wfr = WalkForwardResult(
        windows=[w], metric="sharpe_ratio", metric_direction="maximize",
    )
    assert wfr.oos_sharpe_ratio() == 0.0


def test_oos_max_drawdown_no_drawdown() -> None:
    w = _make_window_result([100.0, 110.0, 120.0])
    wfr = WalkForwardResult(
        windows=[w], metric="sharpe_ratio", metric_direction="maximize",
    )
    assert wfr.oos_max_drawdown() == 0.0


# ---------------------------------------------------------------------------
# WalkForwardResult — deterioration (multi-window)
# ---------------------------------------------------------------------------


def test_deterioration_multi_window() -> None:
    """Deterioration averages IS and OOS metrics across multiple windows."""
    w1 = _make_window_result([100, 110, 120], in_sample_metric=2.0)
    w2 = _make_window_result([100, 105, 108], in_sample_metric=1.0)
    wfr = WalkForwardResult(
        windows=[w1, w2], metric="sharpe_ratio", metric_direction="maximize",
    )
    det = wfr.deterioration()
    if "sharpe_ratio" in det:
        mean_is = (2.0 + 1.0) / 2
        oos1 = w1.oos_result.sharpe_ratio()
        oos2 = w2.oos_result.sharpe_ratio()
        mean_oos = (oos1 + oos2) / 2
        expected = (mean_oos - mean_is) / abs(mean_is)
        assert det["sharpe_ratio"] == pytest.approx(expected, rel=1e-4)


def test_deterioration_zero_is_metric() -> None:
    """When IS metric is ~0, deterioration should be 0.0 (not division error)."""
    w = _make_window_result([100, 110], in_sample_metric=0.0)
    wfr = WalkForwardResult(
        windows=[w], metric="sharpe_ratio", metric_direction="maximize",
    )
    det = wfr.deterioration()
    if "sharpe_ratio" in det:
        assert det["sharpe_ratio"] == 0.0


# ---------------------------------------------------------------------------
# WalkForwardResult — to_dataframe with signal params
# ---------------------------------------------------------------------------


def test_to_dataframe_with_signal_params() -> None:
    w = WindowResult(
        train_start="2020-01-01",
        train_end="2021-12-31",
        test_start="2022-01-01",
        test_end="2022-12-31",
        best_params={
            "sma_cross": {"fast": "sma_fast"},
        },
        in_sample_metric=0.8,
        oos_result=_make_result([100, 105, 110]),
    )
    wfr = WalkForwardResult(
        windows=[w], metric="sharpe_ratio", metric_direction="maximize",
    )
    df = wfr.to_dataframe()
    assert "sma_cross.fast" in df.columns
    assert df["sma_cross.fast"].iloc[0] == "sma_fast"


# ---------------------------------------------------------------------------
# _generate_windows — anchored with custom step
# ---------------------------------------------------------------------------


def test_anchored_with_custom_step() -> None:
    """Anchored mode with a custom step that differs from test_period."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(
        ps, train_period="2Y", test_period="6M", step="3M", anchored=True,
    )
    windows = wf._generate_windows("2018-01-01", "2024-12-31")

    # All train_starts anchored
    for ts, _, _, _ in windows:
        assert ts == "2018-01-01"

    # More windows than default (step=3M < test=6M)
    wf_default = WalkForward(
        ps, train_period="2Y", test_period="6M", anchored=True,
    )
    default_windows = wf_default._generate_windows("2018-01-01", "2024-12-31")
    assert len(windows) > len(default_windows)


def test_rolling_single_window() -> None:
    """Range that fits exactly one train + test window."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    wf = WalkForward(ps, train_period="1Y", test_period="6M")
    # 1Y train + 6M test = 1.5Y; range is exactly 1.5Y so only 1 window
    windows = wf._generate_windows("2020-01-01", "2021-06-30")
    assert len(windows) == 1
    assert windows[0][0] == "2020-01-01"
