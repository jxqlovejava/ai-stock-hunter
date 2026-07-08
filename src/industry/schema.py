# -*- coding: utf-8 -*-
"""行业研究 DTO — 分类/竞争/估值/催化剂/供应链。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Sector Classification
# ---------------------------------------------------------------------------

class SectorLevel(Enum):
    SW1 = "sw1"    # 申万一级
    SW2 = "sw2"    # 申万二级


@dataclass
class SectorClass:
    """行业分类结果。"""
    sw1_code: str = ""           # 申万一级代码 (e.g. "801010")
    sw1_name: str = ""           # 申万一级名称 (e.g. "食品饮料")
    sw2_code: str = ""           # 申万二级代码
    sw2_name: str = ""           # 申万二级名称
    benchmark_index: str = ""    # 行业基准指数代码
    description: str = ""        # 行业简介


# ---------------------------------------------------------------------------
# Competition Analysis
# ---------------------------------------------------------------------------

class BarrierLevel(Enum):
    NONE = "none"           # 无壁垒
    LOW = "low"             # 低壁垒
    MEDIUM = "medium"       # 中等壁垒
    HIGH = "high"           # 高壁垒
    EXTREME = "extreme"     # 极高壁垒


@dataclass
class CompetitionProfile:
    """行业竞争格局分析。"""
    sector_name: str = ""
    # 集中度
    cr5: float = 0.0               # CR5 集中度 0-100
    hhi: float = 0.0               # HHI 指数 0-10000
    concentration_label: str = ""  # 分散/中度集中/高度集中/寡头

    # 壁垒
    entry_barrier: BarrierLevel = BarrierLevel.MEDIUM
    barrier_factors: list[str] = field(default_factory=list)  # 资本/技术/牌照/品牌/规模

    # 竞争烈度
    rivalry_score: float = 50.0    # 0-100 (0=完全竞争, 100=完全垄断)
    substitution_threat: float = 50.0  # 0-100 替代威胁
    supplier_power: float = 50.0       # 0-100 供应商议价力
    buyer_power: float = 50.0          # 0-100 买方议价力

    # 综合
    competition_intensity: float = 50.0  # 0-100 (0=无竞争, 100=极度激烈)
    moat_potential: float = 50.0         # 0-100 (行业层面护城河潜力)


# ---------------------------------------------------------------------------
# Sector Valuation Framework
# ---------------------------------------------------------------------------

class ValuationMethod(Enum):
    PB = "pb"              # 市净率（周期股）
    PE = "pe"               # 市盈率（稳定成长）
    PEG = "peg"             # PEG（高成长）
    PB_ROE = "pb_roe"       # PB-ROE（金融）
    DCF = "dcf"             # 现金流折现（消费）
    EV_EBITDA = "ev_ebitda" # 企业价值倍数（制造业）
    DIVIDEND = "dividend"   # 股息率（公用事业）


@dataclass
class SectorValuation:
    """行业估值框架输出。"""
    sector_name: str = ""
    primary_method: ValuationMethod = ValuationMethod.PE
    secondary_methods: list[ValuationMethod] = field(default_factory=list)
    historical_pe_median: float = 0.0
    historical_pe_p25: float = 0.0
    historical_pe_p75: float = 0.0
    current_pe_percentile: float = 50.0    # 当前PE在历史中的分位数
    fair_value_range: tuple[float, float] = (0.0, 0.0)  # (lower, upper)
    valuation_score: float = 50.0          # 0-100 估值吸引力


# ---------------------------------------------------------------------------
# Supply Chain Deep Map
# ---------------------------------------------------------------------------

class SupplyChainPosition(Enum):
    UPSTREAM = "upstream"       # 上游原材料
    MIDSTREAM = "midstream"     # 中游制造
    DOWNSTREAM = "downstream"   # 下游消费/应用
    SERVICE = "service"         # 服务/平台


@dataclass
class SupplyChainNode:
    """产业链节点。"""
    code: str = ""
    name: str = ""
    position: SupplyChainPosition = SupplyChainPosition.MIDSTREAM
    layer: int = 0                  # 产业链层级 0=最终消费品
    upstream_codes: list[str] = field(default_factory=list)
    downstream_codes: list[str] = field(default_factory=list)
    cost_pass_through: float = 0.5  # 成本传导系数 0-1
    price_elasticity: float = 1.0   # 价格弹性
    bottleneck_score: float = 0.0   # 瓶颈程度 0-100


# ---------------------------------------------------------------------------
# Sector Report (综合)
# ---------------------------------------------------------------------------

@dataclass
class SectorReport:
    """行业综合研究报告。"""
    sector: SectorClass = field(default_factory=SectorClass)
    competition: Optional[CompetitionProfile] = None
    valuation: Optional[SectorValuation] = None
    supply_chain_summary: str = ""

    # 催化剂
    catalysts: list[str] = field(default_factory=list)
    catalyst_score: float = 50.0     # 催化剂强度 0-100

    # 行业景气
    prosperity_score: float = 50.0   # 0-100 景气度
    prosperity_trend: str = "stable" # improving / stable / declining

    # 政策影响
    policy_impact: float = 0.0       # -100 到 +100 (负=不利, 正=有利)
    policy_notes: list[str] = field(default_factory=list)

    # 代表标的
    representative_stocks: list[str] = field(default_factory=list)

    # 综合
    overall_score: float = 50.0      # 0-100
    confidence: float = 0.7
    data_gaps: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
