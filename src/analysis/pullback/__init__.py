# -*- coding: utf-8 -*-
"""回调入场模块 (Pullback Entry)。

A 股「等回调再入场」全流程:
  1. PullbackDetector — 5 步回调检测
  2. AntiManipulationGate — 反操纵验证关卡
  3. PullbackQualityScorer — 回调质量评分
  4. PullbackScanner — 主动扫描引擎
  5. EntryConditionMonitor — 条件单监控

典型用法:
    from src.analysis.pullback import (
        PullbackDetector, AntiManipulationGate,
        PullbackScanner, EntryConditionMonitor,
    )

    # 单票检测
    gate = AntiManipulationGate()
    detector = PullbackDetector(anti_manipulation_gate=gate)
    state = detector.detect("002460", daily_bars, minute_data=minute_df)

    # 批量扫描
    scanner = PullbackScanner(data_provider, detector)
    result = scanner.scan(ScanConfig(symbols=["000001", "002460"]))

    # 条件监控
    monitor = EntryConditionMonitor(detector, data_provider)
    monitor.add("002460", name="赣锋锂业")
    changes = monitor.check_all()
"""

from .schemas import (
    ManipulationCheck,
    PullbackScanResult,
    PullbackState,
    PullbackStatus,
    PullbackTier,
    SupportLevel,
    WatchEntry,
)
from .detector import PullbackDetector
from .anti_manipulation_gate import AntiManipulationGate
from .scorer import PullbackQualityScorer
from .scanner import PullbackScanner, ScanConfig
from .monitor import EntryConditionMonitor

__all__ = [
    "AntiManipulationGate",
    "EntryConditionMonitor",
    "ManipulationCheck",
    "PullbackDetector",
    "PullbackQualityScorer",
    "PullbackScanResult",
    "PullbackScanner",
    "PullbackState",
    "PullbackStatus",
    "PullbackTier",
    "ScanConfig",
    "SupportLevel",
    "WatchEntry",
]
