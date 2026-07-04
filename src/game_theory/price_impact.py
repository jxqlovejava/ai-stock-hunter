# -*- coding: utf-8 -*-
"""差异化价格冲击模型（原则 5）。

不同玩家类型的买卖行为对股价的差异化影响。

Phase 2: 静态框架。Phase 3: 接入龙虎榜数据拟合冲击参数。
"""

from __future__ import annotations

from dataclasses import dataclass

from .players import PlayerType


@dataclass
class PriceImpact:
    """价格冲击轮廓。"""
    player_type: PlayerType
    typical_magnitude: str       # 典型冲击幅度
    duration: str                # 冲击持续时间
    reversal_probability: float  # 均值回归概率
    leading_patterns: list[str]  # 可提前识别的模式


PRICE_IMPACT_PROFILES: list[PriceImpact] = [
    PriceImpact(
        player_type=PlayerType.NATIONAL_TEAM,
        typical_magnitude="单日 +1-3%（蓝筹指数）→ 1-3 月累计 +5-15%",
        duration="1-3 月",
        reversal_probability=0.8,
        leading_patterns=["沪深 300 ETF 量异常", "银行板块逆势上涨"],
    ),
    PriceImpact(
        player_type=PlayerType.INSTITUTIONAL,
        typical_magnitude="季度 +10-30%（重仓股）→ 抱团瓦解 -20-40%",
        duration="3-6 月（上涨）/ 1-2 月（瓦解）",
        reversal_probability=0.7,
        leading_patterns=["公募仓位集中度上升", "新发基金规模暴增"],
    ),
    PriceImpact(
        player_type=PlayerType.HOT_MONEY,
        typical_magnitude="3-5 日 +30-50%（连板）→ 高位出货 -15-30%",
        duration="3-5 日",
        reversal_probability=0.9,  # 几乎必然回归
        leading_patterns=["龙虎榜游资席位活跃", "连板高度突破"],
    ),
    PriceImpact(
        player_type=PlayerType.QUANT,
        typical_magnitude="日内 +0.1-0.5%（高频）→ 累积影响小",
        duration="分钟-小时",
        reversal_probability=0.95,
        leading_patterns=["成交量异常 spike", "买卖价差突变"],
    ),
    PriceImpact(
        player_type=PlayerType.NORTHBOUND,
        typical_magnitude="日 +0.5-2%（持续流入）→ 月 +3-8%",
        duration="日-月级",
        reversal_probability=0.5,
        leading_patterns=["连续 5 日净流入 > 50 亿", "Fed 鸽派信号"],
    ),
    PriceImpact(
        player_type=PlayerType.RETAIL,
        typical_magnitude="日 +0.1-0.3%（分散持仓）→ 牛市中推升波动",
        duration="日级",
        reversal_probability=0.3,
        leading_patterns=["新开户数暴增", "银证转账大额净流入"],
    ),
]
