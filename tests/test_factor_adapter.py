# -*- coding: utf-8 -*-
"""Factor adapter 单元测试。"""

from __future__ import annotations

import pandas as pd

from src.data.factor_pipeline import compute_all_factors
from src.factors.adapter import build_spot_panel


def test_build_spot_panel_maps_columns():
    df = pd.DataFrame({
        "code": ["600519", "000001"],
        "pb": [2.0, 1.0],
        "ps": [1.5, 2.0],
        "dividend_yield": [3.0, 1.0],
    })
    panel = build_spot_panel(df)
    assert "pb" in panel
    assert "ps" in panel
    assert "dividend_yield" in panel
    assert panel["pb"].shape == (1, 2)
    assert panel["pb"].iloc[0, 0] == 2.0


def test_compute_all_factors_registry_mode():
    df = pd.DataFrame({
        "code": ["600519", "000001", "000002"],
        "pb": [2.0, 1.0, 3.0],
        "ps": [1.5, 2.5, 1.0],
        "dividend_yield": [3.0, 1.0, 2.0],
    })
    result = compute_all_factors(df, use_registry=True)
    for col in ["pb_factor", "ps_factor", "dividend_yield_factor", "value_score"]:
        assert col in result.columns
    # 低 PB 得分高
    assert result.loc[1, "pb_factor"] > result.loc[0, "pb_factor"]


def test_compute_all_factors_legacy_mode_unchanged():
    df = pd.DataFrame({
        "code": ["600519", "000001"],
        "pb": [2.0, 1.0],
    })
    result = compute_all_factors(df, use_registry=False)
    assert "pb_factor" in result.columns
    assert "ps_factor" in result.columns
    assert "accruals_factor" in result.columns
