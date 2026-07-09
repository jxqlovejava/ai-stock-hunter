# -*- coding: utf-8 -*-
"""行业分析模块。

借鉴 cyberagent 物理瓶颈框架 + FinceptTerminal 行业数据模型。
"""

from .bottleneck import BottleneckAnalysis, BottleneckType, SupplyChainLayer
from .classifier import SectorClassifier
from .competition import CompetitionAnalyzer
from .research import SectorResearchReporter
from .schema import (
    BarrierLevel,
    CompetitionProfile,
    SectorClass,
    SectorLevel,
    SectorReport,
    SectorValuation,
    StepStatus,
    SupplyChainNode as DeepSupplyChainNode,
    SupplyChainPosition,
    ValuationMethod,
)
from .supply_chain import SUPPLY_CHAINS, SupplyChainDeepMapper, classify_stock
from .valuation import SectorValuationFramework

__all__ = [
    # Legacy
    "BottleneckAnalysis", "BottleneckType", "SupplyChainLayer",
    "SUPPLY_CHAINS", "classify_stock",
    # New: Schema
    "SectorLevel", "SectorClass", "BarrierLevel", "CompetitionProfile",
    "ValuationMethod", "SectorValuation", "SupplyChainPosition",
    "DeepSupplyChainNode", "SectorReport", "StepStatus",
    # New: Engines
    "SectorClassifier", "CompetitionAnalyzer",
    "SectorValuationFramework", "SupplyChainDeepMapper",
    "SectorResearchReporter",
]
