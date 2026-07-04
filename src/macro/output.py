# -*- coding: utf-8 -*-
"""宏观系统化输出 — 统一的宏观分析结果结构。

Phase 6: 借鉴 financial-services macro-rates-monitor 的系统化输出格式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.data.source_citation import SourceCitation


@dataclass
class IndicatorSnapshot:
    """单个宏观指标快照。"""
    name: str  # 指标名称, 如 "M2 增速"
    value: float  # 当前值
    unit: str = "%"  # 单位
    trend: str = "stable"  # accelerating / decelerating / stable
    percentile: Optional[float] = None  # 历史分位 (0-100)
    direction_signal: str = "neutral"  # bullish / bearish / neutral
    source: str = ""  # 数据来源
    citation: Optional[SourceCitation] = None


@dataclass
class MacroSystemizedOutput:
    """货币-信用双象限框架系统化输出。

    借鉴 financial-services 的 macro-rates-monitor 格式，
    适配 A 股的货币-信用分析体系。
    """

    # 总览
    date: str = ""  # 分析日期 YYYY-MM-DD
    regime: str = ""  # 货币信用象限
    regime_confidence: float = 0.5  # 0.0-1.0
    overall_assessment: str = ""  # 2-3 句话宏观评估

    # 指标快照
    indicators: list[IndicatorSnapshot] = field(default_factory=list)

    # 象限矩阵
    quadrant_matrix: dict = field(default_factory=dict)  # {quadrant: {sectors: [...], signal: "..."}}

    # 板块影响
    sector_impact: dict = field(default_factory=dict)  # {sector: impact_description}

    # 仓位建议
    position_advice: str = "neutral"  # aggressive / moderate / defensive / cash
    position_cap: float = 0.80  # 宏观仓位上限

    # 数据溯源
    source_citations: list[SourceCitation] = field(default_factory=list)
    data_freshness: datetime = field(default_factory=datetime.now)

    def to_summary(self) -> str:
        """生成人类可读的宏观摘要。"""
        lines = [
            f"=== 宏观货币信用快照 [{self.date}] ===",
            f"象限: {self.regime} (置信度 {self.regime_confidence:.0%})",
            f"仓位建议: {self.position_advice} (上限 {self.position_cap:.0%})",
            "",
            "--- 关键指标 ---",
        ]
        for ind in self.indicators:
            trend_arrow = {"accelerating": "↑", "decelerating": "↓", "stable": "→"}.get(ind.trend, "→")
            lines.append(
                f"  {ind.name}: {ind.value}{ind.unit} {trend_arrow} "
                f"[{ind.direction_signal}] (来源: {ind.source})"
            )
        lines.append("")
        lines.append("--- 板块影响 ---")
        for sector, impact in self.sector_impact.items():
            lines.append(f"  {sector}: {impact}")
        lines.append("")
        lines.append(f"评估: {self.overall_assessment}")
        return "\n".join(lines)


# 货币信用象限 → 板块映射表
QUADRANT_SECTOR_MAP: dict[str, dict] = {
    "宽货币+宽信用": {
        "sectors": ["成长 (TMT/新能源)", "券商", "消费"],
        "signal": "bullish",
        "description": "流动性充裕 + 信用扩张, 利好风险资产",
        "position": "aggressive",
    },
    "宽货币+紧信用": {
        "sectors": ["公用事业", "必选消费", "医药"],
        "signal": "neutral",
        "description": "货币宽松但信用传导不畅, 防御为主",
        "position": "moderate",
    },
    "紧货币+宽信用": {
        "sectors": ["银行", "保险", "周期"],
        "signal": "neutral",
        "description": "信用扩张但利率上行, 利好价值股",
        "position": "moderate",
    },
    "紧货币+紧信用": {
        "sectors": ["现金", "短债", "防御 (公用/医药)"],
        "signal": "bearish",
        "description": "双紧格局, 全面防御",
        "position": "defensive",
    },
}
