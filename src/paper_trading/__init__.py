# -*- coding: utf-8 -*-
"""模拟交易模块 — 仓位调度信号 → mx-moni 模拟执行 → learner 反馈闭环。

此模块桥接白泽策略信号与东方财富妙想模拟交易系统，
提供从"分析"到"执行验证"的完整闭环。
"""

from .bridge import PaperTradingBridge
from .signal_adapter import SignalAdapter

__all__ = [
    "PaperTradingBridge",
    "SignalAdapter",
]
