# -*- coding: utf-8 -*-
"""基本面深度研究 DTO — 护城河/红旗/估值/管理层/研报。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Moat Analysis
# ---------------------------------------------------------------------------

class MoatWidth(Enum):
    NONE = "none"           # 无护城河
    NARROW = "narrow"       # 窄护城河
    WIDE = "wide"           # 宽护城河
    DOMINANT = "dominant"   # 支配性护城河


class MoatSource(Enum):
    BRAND = "brand"                     # 品牌溢价
    SWITCHING_COST = "switching_cost"   # 转换成本
    NETWORK_EFFECT = "network_effect"   # 网络效应
    SCALE_ECONOMY = "scale_economy"     # 规模经济
    INTANGIBLE = "intangible"           # 无形资产（专利/牌照）


@dataclass
class MoatProfile:
    """护城河分析结果。"""
    symbol: str = ""
    name: str = ""
    overall_width: MoatWidth = MoatWidth.NONE
    moat_score: float = 50.0          # 0-100
    dimensions: dict[str, float] = field(default_factory=lambda: {
        "brand": 50.0, "switching_cost": 50.0,
        "network_effect": 50.0, "scale_economy": 50.0, "intangible": 50.0,
    })
    moat_trend: str = "stable"         # improving / stable / eroding
    key_evidence: list[str] = field(default_factory=list)
    threats: list[str] = field(default_factory=list)
    confidence: float = 0.7


# ---------------------------------------------------------------------------
# Red Flag Detection
# ---------------------------------------------------------------------------

class RedFlagSeverity(Enum):
    INFO = "info"          # 参考信息
    WARNING = "warning"    # 警告
    CRITICAL = "critical"  # 严重红旗


@dataclass
class RedFlag:
    """单个财务红旗。"""
    name: str = ""
    severity: RedFlagSeverity = RedFlagSeverity.WARNING
    score: float = 0.0                 # 红旗得分（偏离正常程度）
    threshold: float = 0.0             # 触发阈值
    actual_value: float = 0.0          # 实际值
    description: str = ""


@dataclass
class RedFlagReport:
    """财务红旗检测报告。"""
    symbol: str = ""
    name: str = ""
    flags: list[RedFlag] = field(default_factory=list)
    m_score: Optional[float] = None          # Beneish M-Score
    m_score_risk: str = "unknown"            # low / medium / high
    f_score: Optional[float] = None           # Piotroski F-Score 0-9
    f_score_quality: str = "unknown"          # weak / moderate / strong
    accruals_quality: str = "unknown"         # good / moderate / poor
    overall_risk: str = "unknown"             # low / medium / high / critical
    total_flags: int = 0
    critical_flags: int = 0


# ---------------------------------------------------------------------------
# DCF Valuation
# ---------------------------------------------------------------------------

@dataclass
class DCFValuation:
    """DCF 估值结果。"""
    symbol: str = ""
    name: str = ""
    fair_value: float = 0.0            # 每股公允价值
    current_price: float = 0.0         # 当前股价
    upside_pct: float = 0.0            # 上行空间 %
    margin_of_safety: float = 0.0      # 安全边际 %

    # 三情景
    bear_case: float = 0.0
    base_case: float = 0.0
    bull_case: float = 0.0

    # 关键假设
    wacc: float = 0.10
    terminal_growth: float = 0.03
    projection_years: int = 10

    # 元信息
    confidence: float = 0.6
    key_sensitivities: list[str] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Management Evaluation
# ---------------------------------------------------------------------------

@dataclass
class ManagementProfile:
    """管理层评估。"""
    symbol: str = ""
    name: str = ""
    capital_allocation: float = 50.0   # 0-100 资本配置能力
    integrity_score: float = 50.0      # 0-100 诚信度
    competency_score: float = 50.0     # 0-100 专业能力
    incentive_alignment: float = 50.0  # 0-100 激励对齐

    # 关键信号
    insider_ownership_pct: float = 0.0
    recent_insider_trades: str = "neutral"  # buying / selling / neutral
    violations_history: list[str] = field(default_factory=list)

    overall_score: float = 50.0        # 综合 0-100
    confidence: float = 0.5


# ---------------------------------------------------------------------------
# Research Report Aggregation
# ---------------------------------------------------------------------------

@dataclass
class AnalystConsensus:
    """分析师一致预期。"""
    symbol: str = ""
    name: str = ""
    n_analysts: int = 0

    # EPS 一致预期
    eps_consensus: float = 0.0
    eps_high: float = 0.0
    eps_low: float = 0.0

    # 评级分布
    buy_count: int = 0
    hold_count: int = 0
    sell_count: int = 0
    consensus_rating: str = "N/A"     # Strong Buy / Buy / Hold / Sell / Strong Sell

    # 目标价
    target_price_mean: float = 0.0
    target_price_high: float = 0.0
    target_price_low: float = 0.0

    # 趋势
    rating_trend: str = "stable"      # improving / stable / downgrading
    eps_revision_trend: str = "stable" # upward / stable / downward


# ---------------------------------------------------------------------------
# Company Deep Research Report
# ---------------------------------------------------------------------------

@dataclass
class CompanyDeepReport:
    """公司深度研究报告。"""
    symbol: str = ""
    name: str = ""
    moat: Optional[MoatProfile] = None
    red_flags: Optional[RedFlagReport] = None
    dcf: Optional[DCFValuation] = None
    management: Optional[ManagementProfile] = None
    consensus: Optional[AnalystConsensus] = None

    # 综合
    overall_score: float = 50.0
    confidence: float = 0.6
    investment_thesis: str = ""
    key_risks: list[str] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
