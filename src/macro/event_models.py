# -*- coding: utf-8 -*-
"""宏观事件因果链分析 — 数据模型。

参考 AI Gold Miner scenarios/models.py + events/models.py:
  - ImpactChannel: 事件→A股的传导路径
  - HistoricalAnalog: 历史类比事件
  - ImpactEstimate: 量化影响估计
  - MacroEvent: 不可变事件模型
  - EventAnalysisReport: 完整分析报告

A 股 7 大传导路径:
  1. 北向资金    — 外资流入/流出
  2. 汇率        — 人民币升/贬值
  3. 风险偏好    — 全球风险情绪
  4. 出口预期    — 关税/贸易政策
  5. 国内政策    — 货币政策/财政刺激
  6. 行业制裁    — 科技/稀土等定向打击
  7. 全球流动性  — Fed/ECB 货币政策
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# 传导路径
# ---------------------------------------------------------------------------


class ChannelDirection(str, Enum):
    BULLISH = "bullish"     # 利好 A 股
    BEARISH = "bearish"     # 利空 A 股
    NEUTRAL = "neutral"     # 中性/不确定


class ChannelMagnitude(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class ChannelTimeframe(str, Enum):
    IMMEDIATE = "immediate"       # 当日
    SHORT_TERM = "short_term"     # 1-5日
    MEDIUM_TERM = "medium_term"   # 1-4周
    LONG_TERM = "long_term"       # 1月以上


A_SHARE_CHANNELS = [
    "北向资金", "汇率", "风险偏好", "美股映射",
    "出口预期", "国内政策", "行业制裁", "全球流动性",
]


@dataclass
class TransmissionChannel:
    """传导路径 — 宏观事件如何影响 A 股。

    参考 AI Gold Miner ImpactChannel.
    """

    channel: str                           # 7 大路径之一
    direction: ChannelDirection            # 对 A 股方向
    magnitude: ChannelMagnitude            # 影响强度
    description: str = ""                  # 传导逻辑
    timeframe: ChannelTimeframe = ChannelTimeframe.SHORT_TERM
    affected_sectors: list[str] = field(default_factory=list)  # 受影响的行业
    confidence: float = 0.7               # 该路径的确定性


# ---------------------------------------------------------------------------
# 历史类比
# ---------------------------------------------------------------------------


@dataclass
class HistoricalAnalog:
    """历史类比事件。

    参考 AI Gold Miner HistoricalAnalog.
    """

    event_name: str                        # 事件名称
    period: str                            # "2020-03"
    market_reaction: str = ""              # 市场反应描述
    shanghai_change_pct: float = 0.0       # 上证涨跌幅
    similarity_score: float = 0.5          # 与当前事件的相似度 0-1
    key_parallels: list[str] = field(default_factory=list)
    key_differences: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 影响估计
# ---------------------------------------------------------------------------


@dataclass
class ImpactEstimate:
    """宏观事件对 A 股的影响量化估计。

    参考 AI Gold Miner PriceImpactEstimate.
    """

    direction: ChannelDirection
    # 上证指数预期变动
    base_case_change_pct: float = 0.0
    bullish_case_change_pct: float = 0.0
    bearish_case_change_pct: float = 0.0
    peak_impact_days: int = 3             # 影响峰值天数
    confidence: float = 0.5
    reasoning: str = ""

    # 个股层面调整
    stock_adjustment: float = 0.0         # 相对大盘的超额影响
    stock_adjustment_reason: str = ""


# ---------------------------------------------------------------------------
# 策略建议
# ---------------------------------------------------------------------------


@dataclass
class EventStrategy:
    """事件驱动的策略建议。

    参考 AI Gold Miner StrategyRecommendation.
    """

    overall_position: str = "观望"          # 激进/谨慎/防御/观望
    suggested_action: str = ""             # 加仓/减仓/对冲/不动
    hedging_suggestions: list[str] = field(default_factory=list)
    monitoring_indicators: list[str] = field(default_factory=list)  # 先行指标
    position_sizing: str = ""             # 仓位建议


# ---------------------------------------------------------------------------
# 宏观事件
# ---------------------------------------------------------------------------


class EventCategory(str, Enum):
    """宏观事件分类。"""
    MONETARY = "monetary"           # 货币政策 (Fed/央行)
    GEOPOLITICAL = "geopolitical"   # 地缘政治
    ECONOMIC_DATA = "economic_data" # 经济数据
    TRADE_POLICY = "trade_policy"   # 贸易/关税
    FINANCIAL_CRISIS = "financial_crisis"  # 金融风险
    COMMODITY = "commodity"         # 大宗商品
    REGULATORY = "regulatory"       # 监管政策
    TECH_SANCTION = "tech_sanction" # 科技制裁
    OTHER = "other"


@dataclass
class MacroEvent:
    """宏观事件 — 不可变事件记录。

    参考 AI Gold Miner Event + PredictionState.
    """

    event_id: str
    title: str                            # "美联储意外加息50bp"
    category: EventCategory
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""                      # 信息来源
    source_url: str = ""
    description: str = ""                 # 事件描述
    # 关键数据点
    key_numbers: dict[str, float] = field(default_factory=dict)  # {"加息幅度": 0.5, "联邦基金利率": 5.5}


# ---------------------------------------------------------------------------
# 完整分析报告
# ---------------------------------------------------------------------------


@dataclass
class EventAnalysisReport:
    """宏观事件因果链完整分析报告。

    参考 AI Gold Miner ScenarioReport.
    """

    report_id: str
    event: MacroEvent
    created_at: datetime = field(default_factory=datetime.now)

    # 分析
    trigger_conditions: list[str] = field(default_factory=list)
    transmission_channels: list[TransmissionChannel] = field(default_factory=list)
    historical_analogs: list[HistoricalAnalog] = field(default_factory=list)
    impact: Optional[ImpactEstimate] = None

    # 策略
    strategy: EventStrategy = field(default_factory=EventStrategy)

    # 监控
    risk_factors: list[str] = field(default_factory=list)

    # 对特定股票的影响
    stock_symbol: str = ""
    stock_impact_summary: str = ""

    @property
    def summary(self) -> str:
        if self.impact is None:
            return f"[{self.event.category.value}] {self.event.title[:60]}..."
        d = self.impact.direction.value
        direction_cn = {"bullish": "利好", "bearish": "利空", "neutral": "中性"}
        return (
            f"[{direction_cn.get(d, d)}] "
            f"基准{self.impact.base_case_change_pct:+.1f}% "
            f"| 置信度{self.impact.confidence:.0%} "
            f"| {self.event.title[:50]}"
        )

    @property
    def net_bullish_score(self) -> float:
        """综合传导路径的净看多得分 -1.0 ~ +1.0。"""
        if not self.transmission_channels:
            return 0.0
        total = 0.0
        for ch in self.transmission_channels:
            sign = 1.0 if ch.direction == ChannelDirection.BULLISH else (-1.0 if ch.direction == ChannelDirection.BEARISH else 0.0)
            weight = {"strong": 0.4, "moderate": 0.25, "weak": 0.1}.get(ch.magnitude.value, 0.15)
            total += sign * weight * ch.confidence
        return max(-1.0, min(1.0, total))
