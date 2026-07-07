# -*- coding: utf-8 -*-
"""技术综合评分 — 趋势/反转/量价/波动/均线 5 维等权合成。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "technical_composite",
    "nickname": "Technical Composite",
    "category": "technical",
    "description": "技术因子综合评分 — 5维(趋势/反转/量价/波动/均线)等权合成0-100分",
    "columns_required": ["close", "high", "low", "volume"],
    "frequency": ["daily"],
    "min_warmup_bars": 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """聚合已计算的子因子得分。

    需要 panel 中已有子因子 DataFrame（由 Registry 逐个计算后注入）。
    无子因子时返回中性分 50。
    """
    sub_factors = {
        "macd_histogram": 0.10,
        "ma_bias": 0.08,
        "dmi_direction": 0.07,
        "rsi_signal": 0.10,
        "kdj_signal": 0.08,
        "short_term_reversal": 0.07,
        "obv_divergence": 0.10,
        "mfi_signal": 0.08,
        "volume_ratio": 0.08,
        "atr_percentile": 0.06,
        "bollinger_position": 0.06,
        "ma_alignment": 0.06,
        "ma_support": 0.06,
    }

    # 按列顺序找第一条可用数据
    first_col = list(panel.values())[0]
    idx = first_col.index
    cols = first_col.columns

    composite = pd.DataFrame(0.0, index=idx, cols=cols)
    total_weight = 0.0

    for factor_id, weight in sub_factors.items():
        df = panel.get(factor_id)
        if df is not None and not df.empty:
            # 对齐索引
            common_idx = composite.index.intersection(df.index)
            common_cols = composite.columns.intersection(df.columns)
            if len(common_idx) > 0 and len(common_cols) > 0:
                composite.loc[common_idx, common_cols] += (
                    df.loc[common_idx, common_cols].fillna(50.0) * weight
                )
                total_weight += weight

    if total_weight > 0:
        composite = composite / total_weight

    return composite.clip(0, 100)
