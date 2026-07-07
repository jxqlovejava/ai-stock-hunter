# -*- coding: utf-8 -*-
"""估值模块 DTO — ValuationPhase, ValuationSubScores, ValuationResult。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.data.source_citation import SourceCitation


class ValuationPhase(str, Enum):
    """估值阶段分类。"""

    DEEP_VALUE = "deep_value"  # PE < 20th 分位, PB < 1x — 深度低估
    FAIR_VALUE = "fair_value"  # PE 20-60th 分位 — 合理估值
    PREMIUM = "premium"        # PE 60-80th 分位 — 溢价
    BUBBLE = "bubble"          # PE > 80th 分位 或 负盈利+高股价 — 泡沫


@dataclass
class ValuationSubScores:
    """估值子维度评分（0-100）。"""

    pe_percentile_score: float = 50.0       # PE 分位：低分位→高分
    pb_percentile_score: float = 50.0       # PB 分位
    peg_score: float = 50.0                 # PEG 评分
    industry_relative_score: float = 50.0   # 行业相对估值
    pb_roe_match_score: float = 50.0        # PB-ROE 匹配度
    dividend_yield_score: float = 50.0      # 股息率评分
    signals_available: int = 0              # 可用信号数
    confidence: float = 0.7                 # 子维度综合信心度


@dataclass
class ValuationResult:
    """估值分析结果。"""

    symbol: str
    name: str
    composite_score: float = 50.0           # 加权综合评分 0-100
    sub_scores: ValuationSubScores = field(default_factory=ValuationSubScores)
    phase: ValuationPhase = ValuationPhase.FAIR_VALUE

    # 原始数值
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    pe_percentile: Optional[float] = None   # 0-100, A股市场分位
    pb_percentile: Optional[float] = None
    pb_justified: Optional[float] = None    # PB-ROE 合理值
    industry_pe_median: Optional[float] = None
    industry_pb_median: Optional[float] = None
    peg_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None

    source_citations: list[SourceCitation] = field(default_factory=list)
    transition_signals: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def is_cheap(self) -> bool:
        """是否处于便宜区间。"""
        return self.composite_score >= 70

    @property
    def is_expensive(self) -> bool:
        """是否处于昂贵区间。"""
        return self.composite_score <= 30

    @property
    def valuation_context(self) -> str:
        """人类可读的估值概述。"""
        pe_str = f"{self.pe_ttm:.1f}" if self.pe_ttm else "N/A"
        pb_str = f"{self.pb:.2f}" if self.pb else "N/A"
        return (
            f"{self.phase.value}: PE={pe_str}, PB={pb_str}, "
            f"综合={self.composite_score:.0f}"
        )

    @property
    def data_completeness(self) -> float:
        """数据完整度 0.0-1.0。"""
        fields = [self.pe_ttm, self.pb, self.pe_percentile, self.peg_ratio]
        return sum(1 for f in fields if f is not None) / len(fields)
