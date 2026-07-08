# -*- coding: utf-8 -*-
"""Alpha Lens — 市场失效 Alpha 检测与追踪模块。

核心理念: 敬畏市场有效性，寻找市场失效的 Alpha。

三层 Alpha 来源:
  1. 信息来源层级 (AlphaSource)      — 逃出信息茧房
  2. 共识-现实缺口 (ConsensusGap)    — 耐心撑过情绪周期
  3. 叙事生命周期   (NarrativeStage)  — 提前挖掘未交易的东西

贯穿白泽全链路准入→裁决：
  - 准入检查: Alpha 机会存在性门禁
  - 多维诊断: Alpha 来源识别
  - 综合裁决: Alpha 质量裁决
  - 仓位调度: Alpha 时序定位
  - 风控执行: Alpha 衰减监控
"""

from .attribution import AlphaAttribution, AttributionReport
from .decay_tracker import AlphaDecay, AlphaDecayTracker
from .factor_backtest import FactorBacktestEngine
from .factor_synthesizer import FactorSynthesizer
from .lens import AlphaLens
from .monitor import AlphaMonitor
from .ranking_engine import RankingEngine
from .schema import (
    AlphaDecayStatus,
    AlphaProfile,
    AlphaSource,
    AlphaSynthesis,
    ConsensusGap,
    FactorBacktestResult,
    FactorScanResult,
    NarrativeLifecycle,
    NarrativeStage,
    RankedStock,
    RankingResult,
    SourceTier,
    SynthesisMethod,
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
    "FactorBacktestResult",
    "FactorScanResult",
    "AlphaSynthesis",
    "SynthesisMethod",
    "RankedStock",
    "RankingResult",
    # Engine
    "AlphaLens",
    "AlphaMonitor",
    "FactorBacktestEngine",
    "AlphaDecayTracker",
    "AlphaDecay",
    "FactorSynthesizer",
    "RankingEngine",
    # Attribution
    "AlphaAttribution",
    "AttributionReport",
]
