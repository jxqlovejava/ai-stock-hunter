"""Tests for TimeSeriesCV — time series cross-validation."""

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from oxq.core.strategy import Strategy
from oxq.core.types import Portfolio
from oxq.indicators.sma import SMA
from oxq.optimize.paramset import ParameterSet
from oxq.optimize.search import _extract_metric
from oxq.optimize.validation import (
    CVResult,
    CVSplit,
    CVSplitResult,
    TimeSeriesCV,
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
    """Create market data spanning the given date range."""
    dates = pd.bdate_range(start, end, tz="UTC")
    n = len(dates)
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
# TimeSeriesCV.__init__
# ---------------------------------------------------------------------------


def test_n_splits_must_be_at_least_2() -> None:
    with pytest.raises(ValueError, match="n_splits must be >= 2"):
        TimeSeriesCV(n_splits=1)


def test_n_splits_minimum_is_2() -> None:
    cv = TimeSeriesCV(n_splits=2)
    assert cv.n_splits == 2


# ---------------------------------------------------------------------------
# TimeSeriesCV.split — expanding mode
# ---------------------------------------------------------------------------


def test_expanding_split_count() -> None:
    cv = TimeSeriesCV(n_splits=5, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    assert len(splits) == 5


def test_expanding_train_starts_at_start() -> None:
    """Expanding mode: all training periods start at the overall start."""
    cv = TimeSeriesCV(n_splits=3, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    for s in splits:
        assert s.train_start == "2018-01-01"


def test_expanding_train_end_grows() -> None:
    """Expanding mode: training end moves forward each split."""
    cv = TimeSeriesCV(n_splits=4, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    train_ends = [pd.Timestamp(s.train_end) for s in splits]
    for i in range(1, len(train_ends)):
        assert train_ends[i] > train_ends[i - 1]


def test_expanding_test_follows_train() -> None:
    """test_start is after train_end."""
    cv = TimeSeriesCV(n_splits=3, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    for s in splits:
        assert pd.Timestamp(s.test_start) > pd.Timestamp(s.train_end)


def test_expanding_no_overlap_between_train_and_test() -> None:
    cv = TimeSeriesCV(n_splits=3, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    for s in splits:
        assert pd.Timestamp(s.train_end) < pd.Timestamp(s.test_start)


# ---------------------------------------------------------------------------
# TimeSeriesCV.split — sliding mode
# ---------------------------------------------------------------------------


def test_sliding_split_count() -> None:
    cv = TimeSeriesCV(n_splits=5, expanding=False)
    splits = cv.split("2018-01-01", "2024-12-31")
    assert len(splits) == 5


def test_sliding_train_starts_advance() -> None:
    """Sliding mode: train_start moves forward each split."""
    cv = TimeSeriesCV(n_splits=4, expanding=False)
    splits = cv.split("2018-01-01", "2024-12-31")
    train_starts = [pd.Timestamp(s.train_start) for s in splits]
    for i in range(1, len(train_starts)):
        assert train_starts[i] > train_starts[i - 1]


def test_sliding_train_size_constant() -> None:
    """Sliding mode: all train windows have the same duration."""
    cv = TimeSeriesCV(n_splits=4, expanding=False)
    splits = cv.split("2018-01-01", "2024-12-31")
    train_durations = [
        (pd.Timestamp(s.train_end) - pd.Timestamp(s.train_start)).days
        for s in splits
    ]
    # All should be the same
    assert len(set(train_durations)) == 1


def test_sliding_test_follows_train() -> None:
    cv = TimeSeriesCV(n_splits=3, expanding=False)
    splits = cv.split("2018-01-01", "2024-12-31")
    for s in splits:
        assert pd.Timestamp(s.test_start) > pd.Timestamp(s.train_end)


# ---------------------------------------------------------------------------
# TimeSeriesCV.split — embargo
# ---------------------------------------------------------------------------


def test_embargo_creates_gap() -> None:
    """Embargo inserts a gap between train_end and test_start."""
    cv = TimeSeriesCV(n_splits=3, embargo_days=5, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    for s in splits:
        gap = (pd.Timestamp(s.test_start) - pd.Timestamp(s.train_end)).days
        # Gap should be at least embargo_days + 1 (the natural 1-day gap)
        assert gap >= 6  # 5 embargo + 1 natural


def test_no_embargo_gap_is_one_day() -> None:
    """Without embargo, test_start is train_end + 1 day."""
    cv = TimeSeriesCV(n_splits=3, embargo_days=0, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    for s in splits:
        gap = (pd.Timestamp(s.test_start) - pd.Timestamp(s.train_end)).days
        assert gap == 1


# ---------------------------------------------------------------------------
# TimeSeriesCV.split — edge cases
# ---------------------------------------------------------------------------


def test_split_clips_to_data_range() -> None:
    cv = TimeSeriesCV(n_splits=3, expanding=True)
    splits = cv.split("2020-01-01", "2022-12-31")
    for s in splits:
        assert pd.Timestamp(s.test_end) <= pd.Timestamp("2022-12-31")


def test_cvsplit_is_frozen() -> None:
    s = CVSplit(
        train_start="2020-01-01",
        train_end="2021-12-31",
        test_start="2022-01-01",
        test_end="2022-12-31",
    )
    with pytest.raises(AttributeError):
        s.train_start = "2019-01-01"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CVResult
# ---------------------------------------------------------------------------


def _make_cv_split_result(values: list[float]) -> CVSplitResult:
    return CVSplitResult(
        split=CVSplit(
            train_start="2020-01-01",
            train_end="2021-12-31",
            test_start="2022-01-01",
            test_end="2022-12-31",
        ),
        best_params={"sma": {"period": 10}},
        in_sample_metric=0.5,
        oos_result=_make_result(values),
    )


def test_cv_result_mean_oos_metric() -> None:
    """mean_oos_metric computes the mean of the metric across all splits."""
    sr1 = _make_cv_split_result([100, 110])  # total_return = 0.10
    sr2 = _make_cv_split_result([100, 120])  # total_return = 0.20
    cvr = CVResult(
        splits=[sr1, sr2],
        metric="total_return",
        metric_direction="maximize",
    )
    expected = (0.10 + 0.20) / 2
    assert cvr.mean_oos_metric() == pytest.approx(expected, rel=1e-4)


def test_cv_result_std_oos_metric() -> None:
    sr1 = _make_cv_split_result([100, 110])
    sr2 = _make_cv_split_result([100, 120])
    cvr = CVResult(
        splits=[sr1, sr2],
        metric="total_return",
        metric_direction="maximize",
    )
    vals = [0.10, 0.20]
    expected = float(np.std(vals, ddof=1))
    assert cvr.std_oos_metric() == pytest.approx(expected, rel=1e-4)


def test_cv_result_std_single_split() -> None:
    sr = _make_cv_split_result([100, 110])
    cvr = CVResult(
        splits=[sr], metric="total_return", metric_direction="maximize",
    )
    assert cvr.std_oos_metric() == 0.0


def test_cv_result_to_dataframe() -> None:
    sr = _make_cv_split_result([100, 105, 110])
    cvr = CVResult(
        splits=[sr], metric="sharpe_ratio", metric_direction="maximize",
    )
    df = cvr.to_dataframe()
    assert len(df) == 1
    assert "train_start" in df.columns
    assert "test_end" in df.columns
    assert "in_sample_metric" in df.columns
    assert "sma.period" in df.columns
    assert "oos_total_return" in df.columns
    assert "oos_sharpe_ratio" in df.columns
    assert "oos_num_trades" in df.columns


def test_cv_result_to_dataframe_no_params() -> None:
    """Split without paramset has no param columns."""
    sr = CVSplitResult(
        split=CVSplit("2020-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
        best_params=None,
        in_sample_metric=None,
        oos_result=_make_result([100, 110]),
    )
    cvr = CVResult(
        splits=[sr], metric="total_return", metric_direction="maximize",
    )
    df = cvr.to_dataframe()
    assert len(df) == 1
    assert df["in_sample_metric"].iloc[0] is None


# ---------------------------------------------------------------------------
# TimeSeriesCV.cross_validate — integration (no paramset)
# ---------------------------------------------------------------------------


def test_cross_validate_without_paramset() -> None:
    """cross_validate without paramset runs the strategy as-is on each fold."""
    data = _make_long_data("2018-01-01", "2024-12-31")
    market = FakeMarketDataProvider(data)

    cv = TimeSeriesCV(n_splits=3, expanding=True)
    result = cv.cross_validate(
        strategy=_make_strategy(),
        market=market,
        broker_factory=SimBroker,
        start="2018-01-01",
        end="2024-12-31",
        metric="sharpe_ratio",
    )

    assert len(result.splits) == 3
    assert result.metric == "sharpe_ratio"
    assert result.metric_direction == "maximize"

    for sr in result.splits:
        assert sr.best_params is None
        assert sr.in_sample_metric is None
        assert isinstance(sr.oos_result, RunResult)
        assert len(sr.oos_result.equity_curve) > 0


# ---------------------------------------------------------------------------
# TimeSeriesCV.cross_validate — integration (with paramset)
# ---------------------------------------------------------------------------


def test_cross_validate_with_paramset() -> None:
    """cross_validate with paramset optimizes per fold."""
    data = _make_long_data("2018-01-01", "2024-12-31")
    market = FakeMarketDataProvider(data)

    ps = ParameterSet("test")
    ps.add("sma_cross", "fast", values=["sma_fast"])

    cv = TimeSeriesCV(n_splits=2, expanding=True)
    result = cv.cross_validate(
        strategy=_make_strategy(),
        market=market,
        broker_factory=SimBroker,
        start="2018-01-01",
        end="2024-12-31",
        paramset=ps,
        metric="sharpe_ratio",
    )

    assert len(result.splits) == 2
    for sr in result.splits:
        assert sr.best_params is not None
        assert sr.in_sample_metric is not None
        assert isinstance(sr.oos_result, RunResult)


# ---------------------------------------------------------------------------
# TimeSeriesCV.split — sliding mode with embargo
# ---------------------------------------------------------------------------


def test_sliding_embargo_creates_gap() -> None:
    """Sliding mode also respects embargo gap."""
    cv = TimeSeriesCV(n_splits=3, embargo_days=5, expanding=False)
    splits = cv.split("2018-01-01", "2024-12-31")
    for s in splits:
        gap = (pd.Timestamp(s.test_start) - pd.Timestamp(s.train_end)).days
        assert gap >= 6  # 5 embargo + 1 natural


def test_sliding_test_size_constant() -> None:
    """Sliding mode: all test windows have the same duration."""
    cv = TimeSeriesCV(n_splits=4, expanding=False)
    splits = cv.split("2018-01-01", "2024-12-31")
    # Exclude last split which may be clipped
    test_durations = [
        (pd.Timestamp(s.test_end) - pd.Timestamp(s.test_start)).days
        for s in splits[:-1]
    ]
    assert len(set(test_durations)) == 1


# ---------------------------------------------------------------------------
# TimeSeriesCV.split — temporal ordering
# ---------------------------------------------------------------------------


def test_expanding_splits_no_future_leakage() -> None:
    """Each split's test period is strictly after all training data."""
    cv = TimeSeriesCV(n_splits=5, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    for s in splits:
        assert pd.Timestamp(s.test_start) > pd.Timestamp(s.train_end)


def test_expanding_later_folds_see_more_data() -> None:
    """Later folds have strictly longer training periods."""
    cv = TimeSeriesCV(n_splits=4, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    train_durations = [
        (pd.Timestamp(s.train_end) - pd.Timestamp(s.train_start)).days
        for s in splits
    ]
    for i in range(1, len(train_durations)):
        assert train_durations[i] > train_durations[i - 1]


def test_splits_cover_full_range() -> None:
    """The last test_end should be close to the overall end date."""
    cv = TimeSeriesCV(n_splits=3, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    last_test_end = pd.Timestamp(splits[-1].test_end)
    overall_end = pd.Timestamp("2024-12-31")
    # Should be within ~1 year of the end
    assert (overall_end - last_test_end).days < 365


# ---------------------------------------------------------------------------
# TimeSeriesCV — n_splits edge cases
# ---------------------------------------------------------------------------


def test_n_splits_2_produces_2_splits() -> None:
    cv = TimeSeriesCV(n_splits=2, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    assert len(splits) == 2


def test_large_n_splits() -> None:
    cv = TimeSeriesCV(n_splits=10, expanding=True)
    splits = cv.split("2018-01-01", "2024-12-31")
    assert len(splits) == 10


# ---------------------------------------------------------------------------
# CVResult — edge cases
# ---------------------------------------------------------------------------


def test_cv_result_mean_oos_metric_single_split() -> None:
    sr = _make_cv_split_result([100, 110])  # total_return = 0.10
    cvr = CVResult(
        splits=[sr], metric="total_return", metric_direction="maximize",
    )
    assert cvr.mean_oos_metric() == pytest.approx(0.10, rel=1e-4)


def test_cv_result_to_dataframe_multiple_splits() -> None:
    sr1 = _make_cv_split_result([100, 110])
    sr2 = _make_cv_split_result([100, 120])
    cvr = CVResult(
        splits=[sr1, sr2], metric="total_return", metric_direction="maximize",
    )
    df = cvr.to_dataframe()
    assert len(df) == 2
    assert df["oos_total_return"].iloc[0] == pytest.approx(0.10, rel=1e-4)
    assert df["oos_total_return"].iloc[1] == pytest.approx(0.20, rel=1e-4)


def test_cv_result_to_dataframe_with_signal_params() -> None:
    sr = CVSplitResult(
        split=CVSplit("2020-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
        best_params={
            "sma_cross": {"fast": "sma_fast"},
        },
        in_sample_metric=0.5,
        oos_result=_make_result([100, 110]),
    )
    cvr = CVResult(
        splits=[sr], metric="sharpe_ratio", metric_direction="maximize",
    )
    df = cvr.to_dataframe()
    assert "sma_cross.fast" in df.columns
    assert df["sma_cross.fast"].iloc[0] == "sma_fast"


# ---------------------------------------------------------------------------
# TimeSeriesCV.cross_validate — sliding mode (integration)
# ---------------------------------------------------------------------------


def test_cross_validate_sliding_mode() -> None:
    """cross_validate works in sliding (non-expanding) mode."""
    data = _make_long_data("2018-01-01", "2024-12-31")
    market = FakeMarketDataProvider(data)

    cv = TimeSeriesCV(n_splits=3, expanding=False)
    result = cv.cross_validate(
        strategy=_make_strategy(),
        market=market,
        broker_factory=SimBroker,
        start="2018-01-01",
        end="2024-12-31",
        metric="sharpe_ratio",
    )

    assert len(result.splits) == 3
    # All OOS results should have data
    for sr in result.splits:
        assert len(sr.oos_result.equity_curve) > 0
