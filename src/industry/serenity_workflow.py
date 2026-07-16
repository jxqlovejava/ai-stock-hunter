# -*- coding: utf-8 -*-
"""Serenity 式主题研究 workflow 原语。

- 双排名：Layer ranking ≠ Company ranking（先层后票）
- 证据阶梯 ↔ 白泽 T0–T3 / nature 映射
- A 股证据 checklist + red flags
- 输出契约：层表 + 公司五列 + 降级热门 + 失败条件 + 下一步

借鉴: https://github.com/muxuuu/serenity-skill
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from .bottleneck import BottleneckType, EvidenceLevel, SupplyChainLayer


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SerenityRole(str, Enum):
    """公司相对稀缺层的角色（比 OWNER 四档更细的研究语言）。"""
    CONTROLS = "controls"              # 控制卡点
    SUPPLIES = "supplies"              # 供应卡点
    BENEFITS = "benefits"              # 受益于趋势，控制力有限
    WEAK_CONTROL = "weak_control"      # 有暴露、定价权弱
    STORY_ONLY = "story_only"          # 主要是故事


class SerenityEvidenceStrength(str, Enum):
    """Serenity 口语证据强度。"""
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"
    NEEDS_CHECKING = "needs_checking"


ROLE_CN = {
    SerenityRole.CONTROLS: "控制卡点",
    SerenityRole.SUPPLIES: "供应卡点",
    SerenityRole.BENEFITS: "趋势受益",
    SerenityRole.WEAK_CONTROL: "弱控制",
    SerenityRole.STORY_ONLY: "纯故事",
}

STRENGTH_CN = {
    SerenityEvidenceStrength.STRONG: "强",
    SerenityEvidenceStrength.MEDIUM: "中",
    SerenityEvidenceStrength.WEAK: "弱",
    SerenityEvidenceStrength.NEEDS_CHECKING: "待核验",
}


# ---------------------------------------------------------------------------
# Layer mapping: Serenity demand-down axis ↔ Baize material-up axis
# ---------------------------------------------------------------------------

# Serenity 8 层（深研 workflow）
SERENITY_LAYERS: Tuple[str, ...] = (
    "end_customers",          # 终端需求 / capex 来源
    "system_integrators",     # 系统集成 / OEM
    "modules_subsystems",     # 模块 / 子系统
    "chips_devices",          # 芯片 / 器件 / 关键部件
    "process_packaging",      # 工艺 / 封装 / 测试
    "equipment_metrology",    # 设备 / 计量
    "materials_consumables",  # 材料 / 耗材
    "physical_infrastructure",  # 物理基建（电力/冷却）
)

SERENITY_LAYER_CN: Dict[str, str] = {
    "end_customers": "终端需求",
    "system_integrators": "系统集成/OEM",
    "modules_subsystems": "模块/子系统",
    "chips_devices": "芯片/器件",
    "process_packaging": "工艺/封装/测试",
    "equipment_metrology": "设备/计量",
    "materials_consumables": "材料/耗材",
    "physical_infrastructure": "物理基建",
}

# Serenity 层名 → 白泽 SupplyChainLayer
SERENITY_TO_BAIZE: Dict[str, SupplyChainLayer] = {
    "end_customers": SupplyChainLayer.END_DEMAND,
    "system_integrators": SupplyChainLayer.SYSTEM,
    "modules_subsystems": SupplyChainLayer.MODULE,
    "chips_devices": SupplyChainLayer.DEVICE,
    "process_packaging": SupplyChainLayer.PACKAGING,
    "equipment_metrology": SupplyChainLayer.EQUIPMENT,
    "materials_consumables": SupplyChainLayer.MATERIAL,
    "physical_infrastructure": SupplyChainLayer.END_DEMAND,  # 旁注基建；无独立枚举时映射终端侧
}

BAIZE_TO_SERENITY: Dict[SupplyChainLayer, str] = {
    SupplyChainLayer.END_DEMAND: "end_customers",
    SupplyChainLayer.SYSTEM: "system_integrators",
    SupplyChainLayer.MODULE: "modules_subsystems",
    SupplyChainLayer.DEVICE: "chips_devices",
    SupplyChainLayer.PACKAGING: "process_packaging",
    SupplyChainLayer.EQUIPMENT: "equipment_metrology",
    SupplyChainLayer.MATERIAL: "materials_consumables",
    SupplyChainLayer.SUBSTRATE: "materials_consumables",
}


# ---------------------------------------------------------------------------
# Evidence mapping
# ---------------------------------------------------------------------------

# Serenity strength → (tier, nature) 建议
SERENITY_TO_TIER_NATURE: Dict[SerenityEvidenceStrength, Tuple[str, str]] = {
    SerenityEvidenceStrength.STRONG: ("T0/T1", "fact"),
    SerenityEvidenceStrength.MEDIUM: ("T1/T2", "interpretation"),
    SerenityEvidenceStrength.WEAK: ("T2/T3", "speculation"),
    SerenityEvidenceStrength.NEEDS_CHECKING: ("T3", "speculation"),
}


def evidence_level_to_serenity(level: EvidenceLevel | str) -> SerenityEvidenceStrength:
    """cyberagent EvidenceLevel → Serenity 口语强度。"""
    val = level.value if isinstance(level, EvidenceLevel) else str(level)
    mapping = {
        "Confirmed": SerenityEvidenceStrength.STRONG,
        "Inferred": SerenityEvidenceStrength.MEDIUM,
        "Weak": SerenityEvidenceStrength.WEAK,
        "Needs verification": SerenityEvidenceStrength.NEEDS_CHECKING,
    }
    return mapping.get(val, SerenityEvidenceStrength.NEEDS_CHECKING)


def tier_nature_to_serenity(
    tier: str = "T2",
    nature: str = "interpretation",
) -> SerenityEvidenceStrength:
    """白泽 tier/nature → Serenity 强度。"""
    t = (tier or "T2").upper()
    n = (nature or "interpretation").lower()
    if n == "speculation" or t in ("T3",):
        return SerenityEvidenceStrength.WEAK
    if t in ("T0", "PRIMARY") and n == "fact":
        return SerenityEvidenceStrength.STRONG
    if t in ("T1", "SECONDARY") and n in ("fact", "interpretation"):
        return SerenityEvidenceStrength.STRONG if n == "fact" else SerenityEvidenceStrength.MEDIUM
    if t in ("T2", "TERTIARY"):
        return SerenityEvidenceStrength.MEDIUM if n != "speculation" else SerenityEvidenceStrength.WEAK
    return SerenityEvidenceStrength.NEEDS_CHECKING


def bottleneck_type_to_serenity_role(btype: BottleneckType | str) -> SerenityRole:
    """OWNER 四档 → Serenity 角色（启发式默认映射）。"""
    val = btype.value if isinstance(btype, BottleneckType) else str(btype).lower()
    mapping = {
        "owner": SerenityRole.CONTROLS,
        "adjacent": SerenityRole.SUPPLIES,
        "derivative": SerenityRole.BENEFITS,
        "none": SerenityRole.STORY_ONLY,
    }
    return mapping.get(val, SerenityRole.STORY_ONLY)


# ---------------------------------------------------------------------------
# A-share evidence checklist & red flags
# ---------------------------------------------------------------------------

A_SHARE_EVIDENCE_CHECKLIST: Tuple[str, ...] = (
    "年报/半年报/季报",
    "临时公告",
    "交易所问询函/监管函",
    "互动易/上证e互动",
    "招投标/中标/客户认证",
    "环评/能评/地方项目备案",
    "专利/标准/协会数据",
    "应收/存货/合同负债/经营现金流",
    "毛利率/产能利用率/在建工程",
    "关联交易/定增/可转债/股权质押/商誉",
)

A_SHARE_RED_FLAGS: Tuple[str, ...] = (
    "论点依赖单一客户传闻",
    "股价主要因社媒/大V驱动",
    "机会兑现前必须先融资",
    "客户匿名且收入影响模糊",
    "应收存货增速显著快于收入",
    "声称稀缺但毛利率不改善",
    "管理层用主题话术但分部收入未变",
)

# 稀缺层信号（用于层排名说明）
SCARCITY_SIGNALS: Tuple[str, ...] = (
    "客户扩产离不开",
    "供应商数量少",
    "认证/验证周期长",
    "扩产需专用设备/许可/know-how/材料纯度",
    "预付款/产能预留/长协/加急订单",
    "市场仍按旧业务分类定价",
)

# AI 半导体强制细分桶（禁止揉成「AI 芯片」一桶）
AI_SEMI_GRANULAR_BUCKETS: Tuple[str, ...] = (
    "算力芯片",
    "EDA/IP",
    "内存/互连",
    "设备",
    "材料/耗材",
    "OSAT/先进封装",
    "光互连",
    "PCB/CCL",
    "电力/冷却基建",
)


# ---------------------------------------------------------------------------
# Dual ranking DTOs
# ---------------------------------------------------------------------------

@dataclass
class LayerRanking:
    """产业链层排名（先于公司）。"""
    rank: int
    layer_key: str                          # SERENITY_LAYERS 或自定义
    layer_name_cn: str
    reason: str
    baize_layer: Optional[SupplyChainLayer] = None
    scarcity_signals: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "layer_key": self.layer_key,
            "layer_name_cn": self.layer_name_cn,
            "reason": self.reason,
            "baize_layer": self.baize_layer.value if self.baize_layer else None,
            "scarcity_signals": list(self.scarcity_signals),
        }


@dataclass
class CompanyResearchRank:
    """公司研究优先级排名（五列契约）。"""
    rank: int
    symbol: str
    name: str
    what_constrains: str = ""       # 卡住的环节
    chain_position: str = ""        # 产业链位置
    rank_reason: str = ""           # 为什么排这里
    evidence: str = ""              # 关键证据
    main_risk: str = ""             # 主要风险
    research_priority_score: float = 0.0
    serenity_role: SerenityRole = SerenityRole.STORY_ONLY
    evidence_strength: SerenityEvidenceStrength = SerenityEvidenceStrength.NEEDS_CHECKING
    failure_conditions: List[str] = field(default_factory=list)
    next_checks: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "symbol": self.symbol,
            "name": self.name,
            "what_constrains": self.what_constrains,
            "chain_position": self.chain_position,
            "rank_reason": self.rank_reason,
            "evidence": self.evidence,
            "main_risk": self.main_risk,
            "research_priority_score": self.research_priority_score,
            "serenity_role": self.serenity_role.value,
            "evidence_strength": self.evidence_strength.value,
            "failure_conditions": list(self.failure_conditions),
            "next_checks": list(self.next_checks),
        }


@dataclass
class ThemeScanResult:
    """主题深扫完整产物（先层后票）。"""
    theme: str = ""
    market: str = "A-share"
    opening_judgment: str = ""
    layer_rankings: List[LayerRanking] = field(default_factory=list)
    company_rankings: List[CompanyResearchRank] = field(default_factory=list)
    downgraded_hot_areas: List[str] = field(default_factory=list)
    next_checks: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)
    is_initial_pass: bool = False
    source_count: int = 0
    candidate_universe_size: int = 0

    def to_dict(self) -> dict:
        return {
            "theme": self.theme,
            "market": self.market,
            "opening_judgment": self.opening_judgment,
            "layer_rankings": [x.to_dict() for x in self.layer_rankings],
            "company_rankings": [x.to_dict() for x in self.company_rankings],
            "downgraded_hot_areas": list(self.downgraded_hot_areas),
            "next_checks": list(self.next_checks),
            "data_gaps": list(self.data_gaps),
            "is_initial_pass": self.is_initial_pass,
            "source_count": self.source_count,
            "candidate_universe_size": self.candidate_universe_size,
        }


# ---------------------------------------------------------------------------
# Format helpers（输出契约）
# ---------------------------------------------------------------------------

def format_theme_opening(
    layer_names: Sequence[str],
    reason: str = "这些地方更接近真实扩产约束",
) -> str:
    """主题扫开头：先排层。"""
    layers = "、".join(layer_names) if layer_names else "（待判定）"
    return (
        f"先排产业链层级，再排公司。"
        f"我会优先看这几层：{layers}。原因是{reason}。"
    )


def format_layer_table(layers: Sequence[LayerRanking]) -> str:
    if not layers:
        return "（无层排名）"
    lines = [
        "| 排名 | 产业链层级 | 排序原因 |",
        "|:---:|:---|:---|",
    ]
    for lr in layers:
        lines.append(f"| {lr.rank} | {lr.layer_name_cn} | {lr.reason} |")
    return "\n".join(lines)


def format_company_table(companies: Sequence[CompanyResearchRank]) -> str:
    """强制五列：标的 / 卡住的环节 / 为什么排这里 / 关键证据 / 主要风险。"""
    if not companies:
        return "（无公司排名）"
    lines = [
        "| 标的 | 卡住的环节 | 为什么排这里 | 关键证据 | 主要风险 |",
        "|:---|:---|:---|:---|:---|",
    ]
    for c in companies:
        label = f"{c.symbol} {c.name}".strip()
        lines.append(
            f"| {label} | {c.what_constrains or '—'} | {c.rank_reason or '—'} "
            f"| {c.evidence or '—'} | {c.main_risk or '—'} |"
        )
    return "\n".join(lines)


def format_challenge_block(
    symbol: str,
    name: str,
    *,
    what_constrains: str,
    chain_position: str,
    serenity_role: SerenityRole,
    evidence: str,
    evidence_strength: SerenityEvidenceStrength,
    failure_conditions: Sequence[str],
    next_checks: Sequence[str],
    research_priority_score: float = 0.0,
) -> str:
    """单票「卡点挑战」小节（diagnose 输出用）。"""
    role_cn = ROLE_CN.get(serenity_role, serenity_role.value)
    str_cn = STRENGTH_CN.get(evidence_strength, evidence_strength.value)
    lines = [
        f"### 🔍 卡点挑战（Serenity）— {symbol} {name}",
        f"- **卡住的环节**: {what_constrains or '未判定'}",
        f"- **产业链位置**: {chain_position or '未判定'}",
        f"- **角色**: {role_cn}（{serenity_role.value}）",
        f"- **研究优先级分**: {research_priority_score:.1f}/100（非买卖指令）",
        f"- **证据强度**: {str_cn} — {evidence or '待搜集'}",
        "- **什么情况说明判断错了**:",
    ]
    fails = list(failure_conditions) or ["（待补充失败条件）"]
    for i, f in enumerate(fails, 1):
        lines.append(f"  {i}. {f}")
    lines.append("- **下一步核验**:")
    checks = list(next_checks) or ["（待列核验清单）"]
    for i, c in enumerate(checks, 1):
        lines.append(f"  {i}. {c}")
    lines.append("- 说明: 按优先研究价值排序，买卖动作由你自己决定。")
    return "\n".join(lines)


def format_theme_scan_report(result: ThemeScanResult) -> str:
    """完整主题扫强制格式。"""
    parts: List[str] = []
    parts.append(f"## 主题深扫: {result.theme or '（未命名）'} [{result.market}]")
    if result.is_initial_pass:
        parts.append(
            f"> ⚠️ **初扫** — 信源 {result.source_count} 条 / 候选宇宙 "
            f"{result.candidate_universe_size}；未达深扫标准（建议 ≥25 源 / ≥20 候选）。"
        )
    opening = result.opening_judgment or format_theme_opening(
        [lr.layer_name_cn for lr in result.layer_rankings[:3]]
    )
    parts.append(opening)
    parts.append("")
    parts.append("### 1. 产业链层排名（先层）")
    parts.append(format_layer_table(result.layer_rankings))
    parts.append("")
    parts.append("### 2. 优先研究公司（后票）")
    parts.append(format_company_table(result.company_rankings))
    parts.append("")
    parts.append("### 3. 降级的热门方向")
    if result.downgraded_hot_areas:
        for d in result.downgraded_hot_areas:
            parts.append(f"- {d}")
    else:
        parts.append("- （必须至少给出一条热门降级理由；当前缺失 → 标记 DATA_GAP）")
    parts.append("")
    parts.append("### 4. 下一步核验")
    checks = result.next_checks or ["补齐公告/财报/客户认证/产能证据"]
    for i, c in enumerate(checks, 1):
        parts.append(f"{i}. {c}")
    if result.data_gaps:
        parts.append("")
        parts.append("### [DATA_GAP]")
        for g in result.data_gaps:
            parts.append(f"- {g}")
    parts.append("")
    parts.append("> 我会按优先研究价值排序。买卖动作由你自己决定。")
    return "\n".join(parts)


def validate_theme_scan_completeness(result: ThemeScanResult) -> List[str]:
    """返回缺失项列表；空列表 = 通过。"""
    gaps: List[str] = []
    if not result.layer_rankings:
        gaps.append("缺少产业链层排名")
    if not result.company_rankings:
        gaps.append("缺少公司研究排名")
    if not result.downgraded_hot_areas:
        gaps.append("缺少至少一条降级热门方向")
    if not result.next_checks:
        gaps.append("缺少下一步核验清单")
    for c in result.company_rankings:
        if not c.what_constrains:
            gaps.append(f"{c.symbol}: 缺少卡住的环节")
        if not c.main_risk:
            gaps.append(f"{c.symbol}: 缺少主要风险")
    if not result.is_initial_pass:
        if result.source_count > 0 and result.source_count < 25:
            gaps.append(f"深扫信源不足 ({result.source_count}<25)，应标初扫或补源")
        if (
            result.candidate_universe_size > 0
            and result.candidate_universe_size < 20
        ):
            gaps.append(
                f"候选宇宙不足 ({result.candidate_universe_size}<20)，应标初扫或扩宇宙"
            )
    return gaps
