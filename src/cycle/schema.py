# -*- coding: utf-8 -*-
"""周期模块 DTO — CyclePhase, CycleAnalysis。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from src.data.source_citation import SourceCitation


class CyclePhase(str, Enum):
    """经济周期五阶段。"""

    RECOVERY = "recovery"        # 复苏 — PMI 突破 50, 政策宽松
    EXPANSION = "expansion"      # 扩张 — PMI > 52, GDP 加速
    PEAK = "peak"                # 顶部 — PMI 回落, 通胀上升
    CONTRACTION = "contraction"  # 收缩 — PMI < 50, 盈利恶化
    TROUGH = "trough"            # 底部 — PMI 企稳, 政策转向


# 周期 → 行业偏好映射
CYCLE_SECTOR_MAP: dict[CyclePhase, tuple[list[str], list[str]]] = {
    CyclePhase.RECOVERY: (
        ["券商", "有色", "化工", "电子", "汽车"],
        ["公用事业", "消费", "医药"],
    ),
    CyclePhase.EXPANSION: (
        ["消费", "科技", "新能源", "医药", "电子"],
        ["公用事业", "现金"],
    ),
    CyclePhase.PEAK: (
        ["银行", "保险", "能源", "公用事业", "消费"],
        ["高估值成长", "券商", "有色"],
    ),
    CyclePhase.CONTRACTION: (
        ["公用事业", "消费", "医药", "现金"],
        ["券商", "有色", "成长", "地产"],
    ),
    CyclePhase.TROUGH: (
        ["券商", "科技", "电子", "基建"],
        ["银行", "地产", "现金"],
    ),
}

# 周期 → 估值调整因子
CYCLE_VALUATION_ADJUSTMENT: dict[CyclePhase, float] = {
    CyclePhase.RECOVERY: 1.20,      # 盈利改善中，估值可适度扩张
    CyclePhase.EXPANSION: 1.10,     # 稳健扩张，估值有支撑
    CyclePhase.PEAK: 0.90,          # 估值有压缩风险
    CyclePhase.CONTRACTION: 0.70,   # 估值压缩，谨慎
    CyclePhase.TROUGH: 0.85,        # 市场见底，早期布局
}


@dataclass
class CycleAnalysis:
    """经济周期分析结果。"""

    phase: CyclePhase
    confidence: float = 0.7

    # 原始信号
    pmi: Optional[float] = None
    pmi_trend: str = "stable"           # rising / falling / stable
    industrial_production: Optional[float] = None  # 工业增加值 YoY %
    gdp_growth: Optional[float] = None  # GDP YoY %
    ppi: Optional[float] = None         # PPI YoY %
    signals_available: int = 0

    # 合成输出
    cycle_score: float = 50.0           # 0-100 股票友好度
    cycle_adjustment_factor: float = 1.0  # 估值乘数调整
    valuation_ceiling_adjustment: float = 1.0

    # 行业偏好
    preferred_sectors: list[str] = field(default_factory=list)
    avoid_sectors: list[str] = field(default_factory=list)

    # 关联宏观
    macro_quadrant: Optional[str] = None

    source_citations: list[SourceCitation] = field(default_factory=list)
    transition_signals: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def is_pro_cycle(self) -> bool:
        """是否处于有利股票的周期阶段。"""
        return self.phase in (CyclePhase.RECOVERY, CyclePhase.EXPANSION)

    @property
    def is_con_cycle(self) -> bool:
        """是否处于不利股票的周期阶段。"""
        return self.phase in (CyclePhase.CONTRACTION, CyclePhase.PEAK, CyclePhase.TROUGH)

    @property
    def earnings_environment(self) -> str:
        """当前盈利环境描述。"""
        mapping: dict[CyclePhase, str] = {
            CyclePhase.RECOVERY: "improving",
            CyclePhase.EXPANSION: "strong",
            CyclePhase.PEAK: "peaking",
            CyclePhase.CONTRACTION: "deteriorating",
            CyclePhase.TROUGH: "bottoming",
        }
        return mapping.get(self.phase, "neutral")

    @property
    def risk_level(self) -> str:
        """风险等级。"low" / "medium" / "high"。"""
        if self.phase == CyclePhase.EXPANSION:
            return "low"
        elif self.phase in (CyclePhase.RECOVERY, CyclePhase.PEAK):
            return "medium"
        return "high"
