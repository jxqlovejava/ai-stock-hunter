"""Tests for AnnualizedVolatility indicator."""

import numpy as np
import pandas as pd
import pytest

from oxq.indicators.annualized_volatility import AnnualizedVolatility


class TestAnnualizedVolatility:
    def test_basic_computation(self):
        """AnnualizedVol = pstdev(simple_returns) * sqrt(252), rolling."""
        prices = [100.0, 102.0, 101.0, 103.0, 105.0, 104.0]
        df = pd.DataFrame({"close": prices})
        result = AnnualizedVolatility().compute(df, column="close", period=3)

        # Manual: simple returns via pct_change
        r1 = 101 / 102 - 1  # -0.009804
        r2 = 103 / 101 - 1  # 0.019802
        r3 = 105 / 103 - 1  # 0.019417
        rets = [r1, r2, r3]
        mean = sum(rets) / 3
        pstd = (sum((r - mean) ** 2 for r in rets) / 3) ** 0.5
        expected = pstd * np.sqrt(252)

        assert result.iloc[4] == pytest.approx(expected, rel=1e-8)

    def test_uses_population_stddev(self):
        """Must use ddof=0 (population), not ddof=1 (sample)."""
        prices = [100.0, 105.0, 100.0, 105.0, 100.0, 105.0, 100.0]
        df = pd.DataFrame({"close": prices})
        result = AnnualizedVolatility().compute(df, column="close", period=4)

        simple_returns = pd.Series(prices).pct_change().dropna()
        sample_std = simple_returns.rolling(4).std(ddof=1).iloc[-1]
        pop_std = simple_returns.rolling(4).std(ddof=0).iloc[-1]

        assert result.iloc[-1] == pytest.approx(pop_std * np.sqrt(252), rel=1e-8)
        assert result.iloc[-1] != pytest.approx(sample_std * np.sqrt(252), rel=1e-4)

    def test_first_values_are_nan(self):
        """First period+1 values should be NaN (1 for diff + period for rolling)."""
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]})
        result = AnnualizedVolatility().compute(df, column="close", period=3)
        assert np.isnan(result.iloc[0])
        assert np.isnan(result.iloc[1])
        assert np.isnan(result.iloc[2])
        assert not np.isnan(result.iloc[3])

    def test_name_attribute(self):
        assert AnnualizedVolatility().name == "AnnualizedVolatility"
