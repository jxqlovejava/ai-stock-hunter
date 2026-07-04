# -*- coding: utf-8 -*-
"""情绪信号检测。

追踪 14 个情绪指标，分三级:
  Level 1: 大盘情绪（每日）— 涨跌比、涨停/跌停数、成交量、北向资金、融资余额
  Level 2: 板块情绪（实时）— 板块涨跌比、板块资金流向、板块新闻情感
  Level 3: 事件驱动（实时）— 突发利空、过度反应、澄清反转、机构分歧、量价背离
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SentimentLevel(str, Enum):
    NORMAL = "NORMAL"
    PANIC = "PANIC"
    GREED = "GREED"
    EXTREME = "EXTREME"  # 极度恐慌 = 可能的抄底机会


@dataclass
class MarketSentiment:
    """大盘情绪快照。"""
    level: SentimentLevel = SentimentLevel.NORMAL
    advance_decline_ratio: float = 1.0   # > 3 = 狂热, < 0.33 = 恐慌
    limit_up_count: int = 0              # 涨停家数
    limit_down_count: int = 0            # 跌停 > 50 = 恐慌蔓延
    volume_ratio: float = 1.0            # vs 20日均量
    northbound_net: float = 0.0          # 北向净买入（亿元）
    margin_change: float = 0.0           # 融资余额变化
    score: int = 50                      # 0=极端恐慌, 100=极端贪婪


class SentimentDetector:
    """情绪信号检测器。"""

    # 阈值常量
    PANIC_AD_RATIO = 0.33         # 涨跌比 < 0.33
    GREED_AD_RATIO = 3.0          # 涨跌比 > 3.0
    PANIC_LIMIT_DOWN = 50         # 跌停 > 50 家
    EXTREME_LIMIT_DOWN = 100      # 跌停 > 100 家 = 极端
    PANIC_VOLUME_SPIKE = 2.0      # 成交量 > 20日均量 2x
    PANIC_NORTHBOUND_OUT = -5.0   # 北向净流出 > 50亿
    EXTREME_NORTHBOUND_OUT = -10.0  # 北向净流出 > 100亿
    GREED_MARGIN_SPIKE = 100       # 融资日增 > 100亿

    def detect_market(
        self,
        advance_decline: float = 1.0,
        limit_up: int = 0,
        limit_down: int = 0,
        volume_ratio: float = 1.0,
        northbound: float = 0.0,
        margin_change: float = 0.0,
    ) -> MarketSentiment:
        """检测大盘情绪。"""
        score = 50
        level = SentimentLevel.NORMAL

        # 恐慌信号
        panic_signals = 0
        if advance_decline < self.PANIC_AD_RATIO:
            panic_signals += 1
            score -= 15
        if limit_down > self.PANIC_LIMIT_DOWN:
            panic_signals += 1
            score -= 10
        if volume_ratio > self.PANIC_VOLUME_SPIKE:
            panic_signals += 1
            score -= 5
        if northbound < self.PANIC_NORTHBOUND_OUT:
            panic_signals += 1
            score -= 10

        # 贪婪信号
        greed_signals = 0
        if advance_decline > self.GREED_AD_RATIO:
            greed_signals += 1
            score += 15
        if margin_change > self.GREED_MARGIN_SPIKE:
            greed_signals += 1
            score += 10

        # 判定
        if limit_down >= self.EXTREME_LIMIT_DOWN or northbound <= self.EXTREME_NORTHBOUND_OUT:
            level = SentimentLevel.EXTREME
        elif panic_signals >= 3:
            level = SentimentLevel.PANIC
        elif greed_signals >= 2:
            level = SentimentLevel.GREED

        return MarketSentiment(
            level=level,
            advance_decline_ratio=advance_decline,
            limit_up_count=limit_up,
            limit_down_count=limit_down,
            volume_ratio=volume_ratio,
            northbound_net=northbound,
            margin_change=margin_change,
            score=max(0, min(100, score)),
        )

    def detect_sector(self, sector_data: dict) -> str:
        """检测板块情绪。简化版——根据板块涨跌比判断。"""
        ratio = sector_data.get("advance_decline", 1.0)
        flow = sector_data.get("capital_flow", 0)  # 资金净流入/流出
        if ratio < 0.5 and flow < 0:
            return "PANIC"
        elif ratio > 2.0 and flow > 0:
            return "GREED"
        return "NORMAL"
