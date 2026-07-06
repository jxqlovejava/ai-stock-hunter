# -*- coding: utf-8 -*-
"""因子注册表单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.registry import Registry, SkipAlpha


@pytest.fixture
def registry():
    return Registry()


@pytest.fixture
def value_panel():
    codes = ["600519", "000001", "000002"]
    index = pd.date_range("2025-01-01", periods=3)
    return {
        "pb": pd.DataFrame(
            {"600519": [2.0, 2.0, 2.0], "000001": [1.0, 1.0, 1.0], "000002": [3.0, 3.0, 3.0]},
            index=index,
        ),
        "ps": pd.DataFrame(
            {"600519": [1.5, 1.5, 1.5], "000001": [2.5, 2.5, 2.5], "000002": [1.0, 1.0, 1.0]},
            index=index,
        ),
        "dividend_yield": pd.DataFrame(
            {"600519": [3.0, 3.0, 3.0], "000001": [1.0, 1.0, 1.0], "000002": [2.0, 2.0, 2.0]},
            index=index,
        ),
    }


def test_registry_scans_zoo(registry):
    ids = registry.list()
    assert "pb_factor" in ids
    assert "ps_factor" in ids
    assert "value_score" in ids
    assert "quality_score" in ids
    assert "growth_score" in ids


def test_compute_pb_factor(registry, value_panel):
    out = registry.compute("pb_factor", value_panel)
    assert out.shape == value_panel["pb"].shape
    # 低 PB 得分高：600519 PB=2 应低于 000001 PB=1
    last = out.iloc[-1]
    assert last["000001"] > last["600519"]
    assert "source_citation" in out.attrs


def compute_quality_panel():
    codes = ["600519", "000001"]
    index = pd.date_range("2025-01-01", periods=2)
    return {
        "net_profit": pd.DataFrame(
            {"600519": [100.0, 100.0], "000001": [80.0, 80.0]},
            index=index,
        ),
        "operating_cashflow": pd.DataFrame(
            {"600519": [120.0, 120.0], "000001": [40.0, 40.0]},
            index=index,
        ),
        "total_assets": pd.DataFrame(
            {"600519": [1000.0, 1000.0], "000001": [800.0, 800.0]},
            index=index,
        ),
    }


def test_compute_quality_score(registry):
    panel = compute_quality_panel()
    out = registry.compute("quality_score", panel)
    assert out.shape == panel["net_profit"].shape
    # 600519 现金流覆盖更好，应得分更高
    last = out.iloc[-1]
    assert last["600519"] > last["000001"]


def test_skip_alpha_on_missing_column(registry, value_panel):
    panel = {k: v for k, v in value_panel.items() if k != "pb"}
    with pytest.raises(SkipAlpha):
        registry.compute("pb_factor", panel)


def test_alpha_output_rejects_inf(registry):
    bad_df = pd.DataFrame({"A": [np.inf, 1.0], "B": [2.0, 3.0]})
    with pytest.raises(ValueError):
        registry._validate_output("bad_alpha", bad_df, {})


def test_alpha_output_rejects_all_nan(registry):
    bad_df = pd.DataFrame({"A": [np.nan, np.nan], "B": [np.nan, np.nan]})
    with pytest.raises(ValueError):
        registry._validate_output("bad_alpha", bad_df, {})
