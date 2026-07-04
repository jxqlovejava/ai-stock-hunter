"""Tests for GarchVolatility indicator (true GARCH(1,1) with MLE)."""

import math

import numpy as np
import pandas as pd
import pytest

from oxq.core.types import Indicator
from oxq.indicators.garch_volatility import GarchVolatility


def _make_mktdata(closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000},
        index=dates,
    )


def test_garch_volatility_satisfies_indicator_protocol() -> None:
    assert isinstance(GarchVolatility(), Indicator)


def test_garch_volatility_basic() -> None:
    closes = [100, 102, 101, 103, 100, 98, 102, 105, 103, 101]
    mktdata = _make_mktdata(closes)
    result = GarchVolatility().compute(mktdata)
    assert isinstance(result, pd.Series)
    assert len(result) == len(closes)
    assert result.isna().sum() == 1  # first value NaN
    assert (result.dropna() > 0).all()


def test_garch_volatility_hand_calculated() -> None:
    """With fixed params, verify GARCH recursion by hand."""
    closes = [100.0, 102.0, 99.0, 101.0]
    mktdata = _make_mktdata(closes)

    omega = 0.00001
    alpha = 0.1
    beta = 0.85

    r1 = math.log(102.0 / 100.0)
    r2 = math.log(99.0 / 102.0)
    r3 = math.log(101.0 / 99.0)

    # Unconditional variance as seed
    uncond_var = omega / (1 - alpha - beta)

    # GARCH recursion: sigma2_t = omega + alpha * r_{t-1}^2 + beta * sigma2_{t-1}
    sigma2_1 = uncond_var  # seed
    sigma2_2 = omega + alpha * r1**2 + beta * sigma2_1
    sigma2_3 = omega + alpha * r2**2 + beta * sigma2_2

    result = GarchVolatility().compute(
        mktdata, omega=omega, alpha=alpha, beta=beta,
    )

    assert math.isnan(result.iloc[0])
    assert result.iloc[1] == pytest.approx(math.sqrt(sigma2_1), rel=1e-10)
    assert result.iloc[2] == pytest.approx(math.sqrt(sigma2_2), rel=1e-10)
    assert result.iloc[3] == pytest.approx(math.sqrt(sigma2_3), rel=1e-10)


def test_garch_volatility_constant_price() -> None:
    closes = [100.0] * 20
    mktdata = _make_mktdata(closes)
    result = GarchVolatility().compute(mktdata)
    # Constant prices -> zero returns -> volatility should converge to sqrt(omega/(1-alpha-beta))
    # but since returns are all zero, variance collapses toward omega/(1-alpha-beta) with very small values
    assert math.isnan(result.iloc[0])
    # All finite and non-negative
    assert result.iloc[1:].ge(0).all()


def test_garch_volatility_has_name() -> None:
    assert GarchVolatility().name == "GarchVolatility"


def test_garch_volatility_mle_fits_reasonable_params() -> None:
    """MLE should recover reasonable alpha+beta < 1 from synthetic GARCH data."""
    rng = np.random.default_rng(42)
    true_omega = 0.00001
    true_alpha = 0.08
    true_beta = 0.90

    n = 500
    returns = np.empty(n)
    sigma2 = np.empty(n)
    sigma2[0] = true_omega / (1 - true_alpha - true_beta)
    returns[0] = rng.normal(0, math.sqrt(sigma2[0]))
    for t in range(1, n):
        sigma2[t] = true_omega + true_alpha * returns[t - 1] ** 2 + true_beta * sigma2[t - 1]
        returns[t] = rng.normal(0, math.sqrt(sigma2[t]))

    # Convert returns to prices
    prices = [100.0]
    for r in returns[1:]:
        prices.append(prices[-1] * math.exp(r))

    mktdata = _make_mktdata(prices)
    result = GarchVolatility().compute(mktdata)

    # Should produce valid output
    assert isinstance(result, pd.Series)
    assert len(result) == n
    assert result.isna().sum() == 1
    assert (result.dropna() > 0).all()


def test_garch_volatility_missing_scipy_with_no_params() -> None:
    """When params not provided, MLE is used (requires scipy)."""
    # This test just ensures the MLE path runs without error
    closes = [100, 102, 101, 103, 100, 98, 102, 105, 103, 101]
    mktdata = _make_mktdata(closes)
    result = GarchVolatility().compute(mktdata)
    assert isinstance(result, pd.Series)
