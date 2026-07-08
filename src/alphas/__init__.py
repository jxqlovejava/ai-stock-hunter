# -*- coding: utf-8 -*-
"""Alpha 模型 — LEAN 风格预测信号生成器。

每个 AlphaModel 接收市场数据并输出方向性信号 (Signal)，
供后续 PortfolioTarget 转换与仓位调度使用。
"""

from .base import AlphaModel
from .ema_cross import EmaCrossAlphaModel
from .macd import MacdAlphaModel
from .rsi import RsiAlphaModel
from .momentum import MomentumAlphaModel

__all__ = [
    "AlphaModel",
    "EmaCrossAlphaModel",
    "MacdAlphaModel",
    "RsiAlphaModel",
    "MomentumAlphaModel",
]
