# -*- coding: utf-8 -*-
"""物理瓶颈分析模型。

借鉴 cyberagent (https://github.com/CyberK13/cyberagent) 的核心框架:
  - 供应链拆解: 材料→衬底→设备→封装→器件→模组→系统→终端
  - 瓶颈分类: owner / adjacent / derivative / none
  - 两轴独立判断: 瓶颈身份(a) × 定价位置(b)
  - 证据分级: Confirmed / Inferred / Weak / NeedsVerification

锚定 Aschenbrenner《Situational Awareness》:
  AI 扩张是工业进程，被物理输入卡住——电力/变压器/燃气轮机 >
  CoWoS 先进封装/HBM > 裸逻辑产能。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BottleneckType(str, Enum):
    """瓶颈身份分类（cyberagent physical department 核心输出）。"""
    OWNER = "owner"              # 拥有者: 拥有绑定约束，再多钱也买不到
    ADJACENT = "adjacent"        # 紧邻: 在瓶颈旁边但不是瓶颈本身
    DERIVATIVE = "derivative"    # 衍生受益者: 间接受益，不控制瓶颈
    NONE = "none"                # 不沾: 与物理瓶颈无关


class SupplyChainLayer(str, Enum):
    """供应链层级（从原材料到终端需求）。"""
    MATERIAL = "material"        # 材料（如高纯红磷、特种气体）
    SUBSTRATE = "substrate"      # 衬底（如 SiC 晶圆、硅片）
    EQUIPMENT = "equipment"      # 设备（如光刻机、刻蚀机、检测设备）
    PACKAGING = "packaging"      # 封装（如 CoWoS、FC-BGA）
    DEVICE = "device"            # 器件（如 HBM、GPU、FPGA）
    MODULE = "module"            # 模组（如光模块、电源模块）
    SYSTEM = "system"            # 系统（如服务器、交换机、机架）
    END_DEMAND = "end_demand"    # 终端需求（如数据中心、AI应用）


class EvidenceLevel(str, Enum):
    """证据分级（cyberagent 标准）。"""
    CONFIRMED = "Confirmed"           # 财报/transcript/IR/官方供应链披露
    INFERRED = "Inferred"             # 行业媒体/sell-side/多家交叉印证
    WEAK = "Weak"                     # 推特/论坛/KOL笔记
    NEEDS_VERIFICATION = "Needs verification"  # 传闻/无原始出处


class PricingPosition(str, Enum):
    """定价位置（两轴之b）。"""
    CHEAP = "cheap"
    FAIR = "fair"
    EXPENSIVE = "expensive"
    PARABOLIC = "parabolic"  # 抛物线尖顶 → AVOID


# ---------------------------------------------------------------------------
# Bottleneck Analysis
# ---------------------------------------------------------------------------

@dataclass
class BottleneckAnalysis:
    """物理瓶颈分析结果。

    借鉴 cyberagent 的 5 步链: 资产定位 → 物理世界 → 人类发展 → 经济学 → 财务。
    这里将核心框架提取为可编程的数据模型。
    """

    # ── Phase 0: 资产定位 ──
    symbol: str
    name: str
    core_business: str = ""                        # 一句话: 它到底卖什么
    supply_chain_layer: SupplyChainLayer = SupplyChainLayer.END_DEMAND
    machine: str = ""                              # 具体机器 (如 "GB300 NVL72 机架")
    sa_ladder_position: str = ""                   # SA 瓶颈阶梯位置

    # ── Physical Department ──
    bottleneck_type: BottleneckType = BottleneckType.NONE
    is_binding_constraint: bool = False            # 是否是"再多钱也买不到"的绑定约束
    constraint_description: str = ""               # 绑定约束描述
    uniqueness: str = ""                           # 唯一性/替代路径
    supply_concentration: str = ""                 # 供应集中度/地缘

    # ── Human Development ──
    development_stage: str = ""                    # 早期/成熟/见顶
    oom_runway: str = ""                           # 还有几个 OOM 的跑道
    sa_alignment: str = ""                         # SA 弧线对齐

    # ── Economics ──
    commercialization: str = ""                    # ore-seller vs processor
    monetizable: bool = False                      # 能否变现
    consensus_status: str = ""                     # 共识状态: underpriced / consensus / overpriced
    is_too_late: bool = False                      # 诚实标"晚了"

    # ── Two-axis verdict ──
    bottleneck_score: float = 0.0                  # 瓶颈身份得分 0-100
    pricing_position: PricingPosition = PricingPosition.FAIR

    # ── Evidence ──
    evidence_summary: dict[str, int] = field(default_factory=lambda: {
        "Confirmed": 0, "Inferred": 0, "Weak": 0, "Needs verification": 0
    })
    load_bearing_weak: bool = False                # 承重声明是否有弱证据
    confidence_cap: float = 1.0                    # 因证据质量封顶的置信度

    @property
    def is_bottleneck_play(self) -> bool:
        """是否是瓶颈相关标的。"""
        return self.bottleneck_type in (
            BottleneckType.OWNER, BottleneckType.ADJACENT
        )

    @property
    def should_avoid(self) -> bool:
        """是否应该回避——尖顶或纯叙事。"""
        return (
            self.is_too_late
            or self.pricing_position == PricingPosition.PARABOLIC
            or (self.bottleneck_type == BottleneckType.NONE
                and self.pricing_position == PricingPosition.EXPENSIVE)
        )


# ---------------------------------------------------------------------------
# SA Bottleneck Ladder
# ---------------------------------------------------------------------------

# Aschenbrenner 瓶颈阶梯 (从最紧张的到相对宽松的)
SA_LADDER = [
    ("电力/变压器/燃气轮机", "power", "新建电厂需3-5年，变压器交付周期18-24月"),
    ("CoWoS 先进封装/HBM", "cowos_hbm", "台积电独供CoWoS，HBM3E仅SK海力士/三星"),
    ("裸逻辑产能", "logic", "3nm以下仅台积电/三星，Intel 18A仍未量产"),
    ("冷却/建设", "cooling", "直接液冷渗透率低，数据中心建设速度受限于许可"),
    ("光互连/网络", "optical", "1.6T光模块刚开始部署，SerDes IP仅少数拥有"),
]

# 供应链层级映射到 SA 阶梯的大致位置
LAYER_TO_LADDER: dict[SupplyChainLayer, str] = {
    SupplyChainLayer.MATERIAL: "材料级——可能卡在特定高纯材料",
    SupplyChainLayer.SUBSTRATE: "衬底级——SiC/GaN衬底产能受限于设备",
    SupplyChainLayer.EQUIPMENT: "设备级——光刻/刻蚀/检测是最大瓶颈",
    SupplyChainLayer.PACKAGING: "封装级——CoWoS是当前最紧的绑定约束",
    SupplyChainLayer.DEVICE: "器件级——HBM是GPU之外的第二瓶颈",
    SupplyChainLayer.MODULE: "模组级——受益于上游紧张但自身不卡",
    SupplyChainLayer.SYSTEM: "系统级——集成商，非瓶颈",
    SupplyChainLayer.END_DEMAND: "终端需求——不沾物理瓶颈",
}
