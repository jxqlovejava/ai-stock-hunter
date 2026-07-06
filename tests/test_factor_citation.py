# -*- coding: utf-8 -*-
"""因子 citation 单元测试。"""

from __future__ import annotations

import pandas as pd

from src.factors.registry import Registry


def test_factor_output_carries_citation():
    reg = Registry()
    panel = {
        "pb": pd.DataFrame(
            {"600519": [2.0], "000001": [1.0]},
            index=pd.date_range("2025-01-01", periods=1),
        )
    }
    out = reg.compute("pb_factor", panel)
    assert "source_citation" in out.attrs
    citation = out.attrs["source_citation"]
    assert citation.provider == "factor_registry"
    assert citation.field == "pb_factor"
    assert citation.nature == "interpretation"
    assert 0.0 < citation.confidence <= 1.0


def test_composite_factor_confidence_bounded_by_inputs():
    reg = Registry()
    from src.data.source_citation import make_citation
    panel = {
        "pb": pd.DataFrame({"600519": [2.0]}, index=pd.date_range("2025-01-01", periods=1)),
        "ps": pd.DataFrame({"600519": [1.5]}, index=pd.date_range("2025-01-01", periods=1)),
        "dividend_yield": pd.DataFrame({"600519": [3.0]}, index=pd.date_range("2025-01-01", periods=1)),
    }
    low_conf = make_citation(provider="llm_derived", field="pb")
    for df in panel.values():
        df.attrs["source_citation"] = low_conf
    out = reg.compute("value_score", panel)
    assert out.attrs["source_citation"].confidence <= 0.45
