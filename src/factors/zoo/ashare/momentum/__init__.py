# -*- coding: utf-8 -*-
"""A 股价格动量因子 — Carhart 动量 + A 股特化版本。

因子:
  - price_momentum_12m1m: 12-1 月动量（经典 Carhart 四因子之一）
  - price_momentum_6m1m:  6-1 月短期动量（A 股短周期动量为正）
  - price_momentum_3m1m:  3-1 月超短动量（A 股特有，1-3 月为强正动量区间）
  - residual_momentum:    残差动量（剔除市场 Beta + 行业 Beta 后）

A 股动量特征:
  - 短周期 (1-3 月): 正动量效应显著（散户追涨）
  - 中周期 (6-12 月): 动量减弱或反转
  - 长周期 (12+ 月): 反转效应主导
"""

from .price_momentum_12m1m import compute as compute_12m1m, __alpha_meta__ as meta_12m1m
from .price_momentum_6m1m import compute as compute_6m1m, __alpha_meta__ as meta_6m1m
from .price_momentum_3m1m import compute as compute_3m1m, __alpha_meta__ as meta_3m1m
from .residual_momentum import compute as compute_residual, __alpha_meta__ as meta_residual

ALL_MOMENTUM_FACTORS = {
    "price_momentum_12m1m": {"compute": compute_12m1m, "meta": meta_12m1m},
    "price_momentum_6m1m": {"compute": compute_6m1m, "meta": meta_6m1m},
    "price_momentum_3m1m": {"compute": compute_3m1m, "meta": meta_3m1m},
    "residual_momentum": {"compute": compute_residual, "meta": meta_residual},
}
