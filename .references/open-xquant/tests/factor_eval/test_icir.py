"""Tests for compute_icir metric."""

from __future__ import annotations

import numpy as np
import pytest

from oxq.factor_eval.metrics import compute_icir


def test_icir_matches_hand_calculation():
    """ICIR = mean / std. Hand-calculate from known values."""
    assert compute_icir(0.2, 0.1) == pytest.approx(2.0)


def test_icir_returns_nan_for_zero_std():
    """ICIR with zero std should return NaN (avoid division by zero)."""
    assert np.isnan(compute_icir(0.05, 0.0))


def test_icir_returns_nan_for_nan_inputs():
    """ICIR with NaN inputs should return NaN."""
    assert np.isnan(compute_icir(float("nan"), 0.1))
