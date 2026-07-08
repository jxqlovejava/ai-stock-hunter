# -*- coding: utf-8 -*-
"""筹码集中度操纵风险 — 前十大持股越高、股东户数下降越快 → 得分越低。"""

from __future__ import annotations

import pandas as pd

from src.factors.base import ts_mean

__alpha_meta__ = {
    "id": "chip_concentration_risk",
    "nickname": "Chip Concentration Risk",
    "category": "technical",
    "description": "筹码集中度操纵风险 — 前十大持股越高、股东户数下降越快 → 得分越低",
    "columns_required": ["top10_holder_pct"],
    "columns_optional": ["shareholder_count"],
    "frequency": ["daily"],
    "min_warmup_bars": 21,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if "top10_holder_pct" not in panel:
        idx = list(panel.values())[0].index
        cols = list(panel.values())[0].columns
        return pd.DataFrame(50.0, index=idx[-1:], columns=cols)

    concentration = panel["top10_holder_pct"]

    # 如果有股东户数数据：户数下降（集中度上升中的一个子维度）放大风险
    if "shareholder_count" in panel and not panel["shareholder_count"].empty:
        shareholders = panel["shareholder_count"].astype(float)
        avg_sh = ts_mean(shareholders, 20)
        decline_rate = (avg_sh - shareholders) / avg_sh.clip(lower=1)
        # 股东加速下降 → 有效集中度上浮（仅正半轴，即下降才放大）
        effective = concentration * (1.0 + decline_rate.clip(lower=0))
    else:
        effective = concentration

    # score = 100 - 集中度 × 0.8；集中度越高得分越低（操纵风险越高）
    score = 100.0 - effective * 0.8
    return score.clip(lower=0, upper=100)
