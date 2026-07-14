# -*- coding: utf-8 -*-
"""白泽持仓哨兵 — 轻量盘中预警（Hermes cron 友好）。

设计:
  - 只盯 positions.json，不跑全链路 diagnose
  - 无异动 stdout 为空 → Hermes 静默不推送
  - 有异动打印短卡片 → 微信投递
"""

from .engine import SentinelConfig, SentinelEngine, SentinelResult
from .models import AlertLevel, PositionSnapshot, SentinelAlert

__all__ = [
    "AlertLevel",
    "PositionSnapshot",
    "SentinelAlert",
    "SentinelConfig",
    "SentinelEngine",
    "SentinelResult",
]
