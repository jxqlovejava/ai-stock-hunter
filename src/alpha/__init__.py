# -*- coding: utf-8 -*-
"""Alpha Lens — 市场失效 Alpha 检测与追踪模块。

核心理念: 敬畏市场有效性，寻找市场失效的 Alpha。

三层 Alpha 来源:
  1. 信息来源层级 (AlphaSource)      — 逃出信息茧房
  2. 共识-现实缺口 (ConsensusGap)    — 耐心撑过情绪周期
  3. 叙事生命周期   (NarrativeStage)  — 提前挖掘未交易的东西

贯穿白泽全链路 L0→L4：
  - L0 Gate: Alpha 机会存在性门禁
  - L1 Analyze: Alpha 来源识别
  - L2 Judge: Alpha 质量裁决
  - L3 Trade: Alpha 时序定位
  - L4 Risk: Alpha 衰减监控
"""

from .attribution import AlphaAttribution, AttributionReport
from .lens import AlphaLens
from .monitor import AlphaMonitor
from .schema import (
    AlphaDecayStatus,
    AlphaProfile,
    AlphaSource,
    ConsensusGap,
    NarrativeLifecycle,
    NarrativeStage,
    SourceTier,
)

__all__ = [
    # Schema
    "SourceTier",
    "NarrativeLifecycle",
    "AlphaDecayStatus",
    "AlphaSource",
    "ConsensusGap",
    "NarrativeStage",
    "AlphaProfile",
    # Engine
    "AlphaLens",
    "AlphaMonitor",
    # Attribution
    "AlphaAttribution",
    "AttributionReport",
]
