# -*- coding: utf-8 -*-
"""关键行业供应链映射。

手动维护 A 股关键行业的核心供应链节点。
借鉴 cyberagent 的方法论: 先把机器拆开，找那个堵点。
"""

from __future__ import annotations

from dataclasses import dataclass

from .bottleneck import BottleneckType, SupplyChainLayer

# ---------------------------------------------------------------------------
# Supply Chain Node
# ---------------------------------------------------------------------------


@dataclass
class SupplyChainNode:
    """供应链节点。"""
    name: str                          # 节点名称
    layer: SupplyChainLayer            # 所在层级
    bottleneck_type: BottleneckType    # 瓶颈分类
    description: str                   # 描述
    a_share_tickers: list[str]         # A 股关联标的
    constraint: str = ""               # 绑定约束（若是瓶颈）


# ---------------------------------------------------------------------------
# Key Supply Chains
# ---------------------------------------------------------------------------


AI_SEMICONDUCTOR = [
    SupplyChainNode(
        name="高纯红磷/特种气体", layer=SupplyChainLayer.MATERIAL,
        bottleneck_type=BottleneckType.ADJACENT,
        description="HBM 封装用 6N 红磷，全球仅少数供应商",
        a_share_tickers=["002409", "300346", "300655"],
        constraint="6N 红磷产能扩张需 2-3 年",
    ),
    SupplyChainNode(
        name="SiC 衬底", layer=SupplyChainLayer.SUBSTRATE,
        bottleneck_type=BottleneckType.ADJACENT,
        description="SiC 晶圆产能集中在 Wolfspeed/Coherent/天科合达/山东天岳",
        a_share_tickers=["688234", "300316"],
        constraint="8 英寸 SiC 良率仍低",
    ),
    SupplyChainNode(
        name="半导体设备", layer=SupplyChainLayer.EQUIPMENT,
        bottleneck_type=BottleneckType.ADJACENT,
        description="光刻/刻蚀/薄膜沉积/检测，国产替代进行中但高端仍被卡",
        a_share_tickers=["002371", "688012", "688072", "300604"],
        constraint="EUV 光刻机被禁运，高端刻蚀设备受限",
    ),
    SupplyChainNode(
        name="先进封装 (CoWoS)", layer=SupplyChainLayer.PACKAGING,
        bottleneck_type=BottleneckType.OWNER,
        description="台积电独供 CoWoS 先进封装，产能是 AI 芯片最大瓶颈",
        a_share_tickers=["002156", "603005", "688256"],
        constraint="台积电 CoWoS 月产能 2025 年约 4 万片，远低于需求",
    ),
    SupplyChainNode(
        name="HBM 内存", layer=SupplyChainLayer.DEVICE,
        bottleneck_type=BottleneckType.OWNER,
        description="HBM3E 仅 SK 海力士/三星能供，是 GPU 之外的第二大瓶颈",
        a_share_tickers=["603986", "002049"],
        constraint="HBM 产能被 AI 需求挤压，DRAM 厂商优先扩 HBM",
    ),
    SupplyChainNode(
        name="光模块 (1.6T)", layer=SupplyChainLayer.MODULE,
        bottleneck_type=BottleneckType.ADJACENT,
        description="1.6T 光模块刚开始部署，受益于 AI 集群 scale-out",
        a_share_tickers=["300308", "300502", "688205"],
        constraint="EML/硅光芯片产能受限",
    ),
    SupplyChainNode(
        name="AI 服务器/交换机", layer=SupplyChainLayer.SYSTEM,
        bottleneck_type=BottleneckType.DERIVATIVE,
        description="集成商，受益于 AI 资本开支但不控制瓶颈",
        a_share_tickers=["000977", "002230", "600850"],
        constraint="",
    ),
    SupplyChainNode(
        name="数据中心/算力租赁", layer=SupplyChainLayer.END_DEMAND,
        bottleneck_type=BottleneckType.NONE,
        description="终端需求方，不沾物理瓶颈（但可以吃需求溢出）",
        a_share_tickers=["300383", "600845", "603881"],
        constraint="",
    ),
]


NEW_ENERGY = [
    SupplyChainNode(
        name="锂矿/锂盐", layer=SupplyChainLayer.MATERIAL,
        bottleneck_type=BottleneckType.ADJACENT,
        description="锂资源集中在澳洲/南美/中国盐湖",
        a_share_tickers=["002460", "002466", "000408"],
        constraint="优质锂矿开发周期 3-5 年",
    ),
    SupplyChainNode(
        name="正极/负极/电解液/隔膜", layer=SupplyChainLayer.SUBSTRATE,
        bottleneck_type=BottleneckType.DERIVATIVE,
        description="四大主材，产能扩张快于需求",
        a_share_tickers=["300750", "002074", "300014", "002812"],
        constraint="产能过剩，非瓶颈",
    ),
    SupplyChainNode(
        name="光伏硅料/硅片", layer=SupplyChainLayer.SUBSTRATE,
        bottleneck_type=BottleneckType.DERIVATIVE,
        description="硅料产能过剩，价格已从高点跌 80%",
        a_share_tickers=["600438", "002129", "688599"],
        constraint="产能严重过剩，非瓶颈",
    ),
    SupplyChainNode(
        name="储能系统", layer=SupplyChainLayer.MODULE,
        bottleneck_type=BottleneckType.ADJACENT,
        description="大储/工商业储能需求快速增长，但电芯供给充足",
        a_share_tickers=["300274", "300068", "300763"],
        constraint="电芯不缺，系统集成商利润薄",
    ),
    SupplyChainNode(
        name="电力设备/变压器", layer=SupplyChainLayer.EQUIPMENT,
        bottleneck_type=BottleneckType.OWNER,
        description="变压器交付周期 18-24 个月，是新能源并网最大瓶颈",
        a_share_tickers=["600089", "601877", "002202"],
        constraint="全球变压器产能严重不足，交付周期 > 18 月",
    ),
]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# 所有供应链节点的统一索引
_ALL_NODES: dict[str, SupplyChainNode] = {}

for _node in AI_SEMICONDUCTOR + NEW_ENERGY:
    for _ticker in _node.a_share_tickers:
        _ALL_NODES[_ticker] = _node

SUPPLY_CHAINS: dict[str, list[SupplyChainNode]] = {
    "AI & Semiconductor": AI_SEMICONDUCTOR,
    "New Energy": NEW_ENERGY,
}


def classify_stock(symbol: str) -> SupplyChainNode | None:
    """根据股票代码在供应链映射表中查找。"""
    return _ALL_NODES.get(symbol)
