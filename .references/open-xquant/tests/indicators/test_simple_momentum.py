"""Tests for SimpleMomentum indicator."""

import numpy as np
import pandas as pd
import pytest

from oxq.indicators.simple_momentum import SimpleMomentum


class TestSimpleMomentum:
    def test_basic_computation(self):
        """SimpleMomentum = (P_t / P_{t-N} - 1) / N"""
        prices = [100.0, 102.0, 104.0, 103.0, 105.0, 110.0]
        df = pd.DataFrame({"close": prices})
        result = SimpleMomentum().compute(df, column="close", period=3)

        # At index 3: (103/100 - 1) / 3 = 0.03/3 = 0.01
        assert result.iloc[3] == pytest.approx(0.01, abs=1e-10)
        # At index 4: (105/102 - 1) / 3
        assert result.iloc[4] == pytest.approx((105 / 102 - 1) / 3, abs=1e-10)
        # At index 5: (110/104 - 1) / 3  (P_{t-N} = prices[2] = 104)
        assert result.iloc[5] == pytest.approx((110 / 104 - 1) / 3, abs=1e-10)

    def test_first_n_values_are_nan(self):
        """First `period` values should be NaN."""
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0, 104.0]})
        result = SimpleMomentum().compute(df, column="close", period=3)
        assert all(np.isnan(result.iloc[:3]))
        assert not np.isnan(result.iloc[3])

    def test_differs_from_log_momentum(self):
        """SimpleMomentum uses simple returns, not log returns."""
        df = pd.DataFrame({"close": [100.0, 110.0, 120.0, 130.0, 150.0]})
        from oxq.indicators.momentum import Momentum

        simple = SimpleMomentum().compute(df, column="close", period=2)
        log = Momentum().compute(df, column="close", period=2)
        # They should differ for non-trivial price changes
        assert simple.iloc[3] != pytest.approx(log.iloc[3], abs=1e-6)

    def test_name_attribute(self):
        assert SimpleMomentum().name == "SimpleMomentum"
