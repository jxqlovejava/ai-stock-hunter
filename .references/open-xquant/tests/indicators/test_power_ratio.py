"""Tests for PowerRatio indicator."""

import numpy as np
import pandas as pd

from oxq.indicators.power_ratio import PowerRatio


class TestPowerRatio:
    def test_exponent_one_equals_ratio(self):
        """With exponent=1.0, PowerRatio == col_a / col_b."""
        df = pd.DataFrame({"a": [10.0, 20.0, 30.0], "b": [2.0, 4.0, 5.0]})
        result = PowerRatio().compute(df, col_a="a", col_b="b", exponent=1.0)
        expected = pd.Series([5.0, 5.0, 6.0])
        pd.testing.assert_series_equal(result, expected)

    def test_exponent_half(self):
        """With exponent=0.5, PowerRatio == col_a / sqrt(col_b)."""
        df = pd.DataFrame({"a": [10.0, 20.0], "b": [4.0, 16.0]})
        result = PowerRatio().compute(df, col_a="a", col_b="b", exponent=0.5)
        expected = pd.Series([5.0, 5.0])
        pd.testing.assert_series_equal(result, expected)

    def test_nan_propagation(self):
        """NaN in inputs should produce NaN in output."""
        df = pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": [1.0, 2.0, np.nan]})
        result = PowerRatio().compute(df, col_a="a", col_b="b", exponent=0.5)
        assert not np.isnan(result.iloc[0])
        assert np.isnan(result.iloc[1])
        assert np.isnan(result.iloc[2])

    def test_name_attribute(self):
        assert PowerRatio().name == "PowerRatio"
