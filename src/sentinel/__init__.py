# -*- coding: utf-8 -*-
"""白泽持仓哨兵 — 轻量盘中预警 + 多频道微信推送（Hermes cron 友好）。

设计:
  - 持仓硬规则 + 大盘/板块/两融背景
  - 两融 / 自选扫雷 / 开收盘简报 / 情绪极端
  - 无异动 stdout 为空 → Hermes 静默不推送
  - 有异动打印人话卡片 → 微信投递
"""

from .engine import SentinelConfig, SentinelEngine, SentinelResult
from .models import AlertLevel, PortfolioLimits, PositionSnapshot, SentinelAlert

__all__ = [
    "AlertLevel",
    "PortfolioLimits",
    "PositionSnapshot",
    "SentinelAlert",
    "SentinelConfig",
    "SentinelEngine",
    "SentinelResult",
]
