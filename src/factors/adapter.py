# -*- coding: utf-8 -*-
"""因子注册表与现有 factor_pipeline 的适配器。

提供从 spot DataFrame（每行一只股票）到宽面板（每个字段一个 DataFrame）的转换，
并支持调用 registry 计算 alpha。
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from src.data.source_citation import make_citation
from src.factors.registry import Registry, get_default_registry


# 字段名映射：从常见列名到 registry 使用的标准名
_FIELD_ALIASES: dict[str, list[str]] = {
    "pb": ["pb", "PB", "市净率"],
    "ps": ["ps", "PS", "市销率"],
    "dividend_yield": ["dividend_yield", "div_yield", "股息率"],
    "net_profit": ["net_profit", "净利润", "net_profit_ttm"],
    "operating_cashflow": ["operating_cashflow", "经营现金流", "ocf"],
    "total_assets": ["total_assets", "总资产", "total_asset"],
    "revenue_growth": ["revenue_growth", "营收增速", "rev_yoy"],
    "earnings_growth": ["earnings_growth", "净利润增速", "profit_yoy", "earnings_yoy"],
}


def _resolve_field(df: pd.DataFrame, standard: str) -> Optional[str]:
    """从 DataFrame 列名中解析标准字段名。"""
    for alias in _FIELD_ALIASES.get(standard, [standard]):
        if alias in df.columns:
            return alias
    return None


def build_spot_panel(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """把 spot DataFrame 转换为 registry 可用的宽面板（单日期）。"""
    # 使用行索引作为 code；若没有 code 列，使用原索引
    codes = df.get("code", df.index)
    if isinstance(codes, pd.DataFrame):
        codes = codes.iloc[:, 0]
    codes = codes.astype(str)

    panel: dict[str, pd.DataFrame] = {}
    for standard in _FIELD_ALIASES:
        col = _resolve_field(df, standard)
        if col is None:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        panel[standard] = pd.DataFrame({code: [value] for code, value in zip(codes, series)})
        panel[standard].attrs["source_citation"] = make_citation(
            provider="factor_pipeline",
            field=standard,
            data_type="factor",
        )
    return panel


def compute_registry_factors(
    df: pd.DataFrame,
    registry: Optional[Registry] = None,
) -> pd.DataFrame:
    """使用 registry 计算因子并追加到原 DataFrame。"""
    reg = registry or get_default_registry()
    panel = build_spot_panel(df)
    result = df.copy()

    for alpha_id in reg.list():
        try:
            score_df = reg.compute(alpha_id, panel)
        except Exception:
            continue
        # score_df 是单行的宽面板；转回列
        if score_df.shape[0] == 1:
            result[alpha_id] = score_df.iloc[0].reindex(df.get("code", df.index).astype(str)).values
        else:
            # 多日面板，暂不处理
            continue
    return result
