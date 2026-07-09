# -*- coding: utf-8 -*-
"""盯盘监控包 — 短线/波段模式下的实时预警与机会发现。

组件:
  - Watchdog: 主调度引擎，定时轮询行情并聚合并发检测器输出
  - OpportunityDetector: 短线机会发现（突破/金叉/板块联动/游资异动）
  - RiskMonitor: 短线风险监控（连板中断/天地板/流动性枯竭/北向突变）
  - Scheduler: 定时调度器（盘中高频 30s-5min，盘后低频 1h）

Monitor Event 系统 (v2.0 — 融资融券/大宗/北向/技术面持续观测):
  - MonitorEvent, MonitorStatus, MonitorType (models)
  - MonitorStore: JSONL 存储 + 状态变更 (store)
  - MonitorSignalGenerator: 事件 → 管线信号 (signals)

Ref: ai-gold-miner events/models.py + events/store.py + signals/monitor_signal.py.
"""

from .models import MonitorEvent, MonitorStatus, MonitorType
from .store import MonitorStore
from .signals import MonitorSignalGenerator, MonitorSignal, generate_monitor_signals

__all__ = [
    # 原有组件 (保持不变)
    # "Watchdog", "OpportunityDetector", "RiskMonitor",
    # Monitor Event v2
    "MonitorEvent",
    "MonitorStatus",
    "MonitorType",
    "MonitorStore",
    "MonitorSignalGenerator",
    "MonitorSignal",
    "generate_monitor_signals",
]
