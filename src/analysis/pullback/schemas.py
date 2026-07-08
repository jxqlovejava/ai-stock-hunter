# -*- coding: utf-8 -*-
"""回调入场模块 — 数据模型定义。

回调状态分类:
  PULLBACK_NONE    — 未在回调中（创新高/横盘）
  PULLBACK_ACTIVE  — 正在回调中（持续下跌，未止跌）
  PULLBACK_SETUP   — 回调到位+止跌确认（可入场候选）
  PULLBACK_TRAP    — 回调到位但检测到操纵信号（禁止入场）
  PULLBACK_BREAK   — 回调失败，破位继续下跌
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PullbackStatus(str, Enum):
    """回调状态枚举。"""
    NONE = "PULLBACK_NONE"       # 未在回调中
    ACTIVE = "PULLBACK_ACTIVE"   # 正在回调，尚未止跌
    SETUP = "PULLBACK_SETUP"     # 回调到位 + 止跌确认
    TRAP = "PULLBACK_TRAP"       # 操纵陷阱，禁止入场
    BREAK = "PULLBACK_BREAK"     # 破位，回调失败


class PullbackTier(str, Enum):
    """回调候选等级（扫描输出用）。"""
    READY = "READY"      # 🟢 可入场
    WATCH = "WATCH"      # 🟡 观察中，接近触发
    BLOCKED = "BLOCKED"  # 🔴 禁止（陷阱/破位）


@dataclass
class SupportLevel:
    """支撑位信息。"""
    price: float
    label: str           # "MA20" | "MA60" | "前低" | "Fib0.382" | "Fib0.618"
    strength: float      # 0.0-1.0 支撑强度


@dataclass
class ManipulationCheck:
    """反操纵验证结果。"""
    risk_score: float = 0.0                # 操纵风险分 0-100
    risk_level: str = "low"               # "high" / "medium" / "low"
    signals_matched: list[str] = field(default_factory=list)
    is_trap: bool = False                  # 是否为诱多陷阱
    is_shakeout: bool = False              # 是否为洗盘震仓
    repeat_offender: bool = False          # 历史 repeat_offender
    sentiment_context: str = ""            # 情绪-操纵联动场景
    confidence_adjustment: float = 0.0     # 联动置信度调整
    suggestion: str = ""                   # 操作建议


@dataclass
class PullbackState:
    """回调检测完整结果。"""

    symbol: str
    name: str = ""
    status: PullbackStatus = PullbackStatus.NONE
    timestamp: datetime = field(default_factory=datetime.now)

    # ── 回调基本数据 ──
    high_20d: float = 0.0              # 20 日最高点
    high_20d_date: str = ""            # 最高点日期
    from_high_pct: float = 0.0         # 从高点回落幅度 (负值，如 -0.08 = -8%)
    days_in_pullback: int = 0          # 已回调天数
    current_price: float = 0.0

    # ── 支撑位 ──
    supports: list[SupportLevel] = field(default_factory=list)
    nearest_support: float = 0.0       # 最近有效支撑位价格
    support_distance_pct: float = 0.0  # 距支撑位距离 (正=在支撑上方，负=已跌破)

    # ── 量价 ──
    volume_shrink_ratio: float = 1.0   # 缩量比 (近2日均量 / 5日均量)
    consecutive_low_stop: int = 0      # 连续不创新低天数
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0

    # ── 操纵检测 ──
    manipulation: Optional[ManipulationCheck] = None

    # ── 综合输出 ──
    pullback_score: float = 50.0        # 回调质量分 0-100
    authentic_pullback: bool = False    # 是否真回调（通过反操纵验证）
    trigger_price: float = 0.0          # 入场触发价
    stop_loss: float = 0.0              # 止损位（支撑下方 1-2%）
    entry_condition: str = ""           # 入场条件描述
    tier: PullbackTier = PullbackTier.BLOCKED

    # ── 数据溯源 ──
    data_freshness: str = ""
    source_citations: list = field(default_factory=list)


@dataclass
class PullbackScanResult:
    """回调扫描汇总。"""
    scan_time: datetime = field(default_factory=datetime.now)
    total_scanned: int = 0
    ready: list[PullbackState] = field(default_factory=list)     # 🟢
    watch: list[PullbackState] = field(default_factory=list)     # 🟡
    blocked: list[PullbackState] = field(default_factory=list)   # 🔴
    data_gaps: list[str] = field(default_factory=list)


@dataclass
class WatchEntry:
    """条件监控条目（持久化到 data/pullback_watch.json）。"""
    symbol: str
    name: str = ""
    added_at: str = ""                          # ISO datetime
    trigger_price: float = 0.0
    trigger_condition: str = ""                 # 触发条件描述
    last_check_at: str = ""
    last_status: PullbackStatus = PullbackStatus.NONE
    condition_met_count: int = 0                # 连续满足次数
    notified: bool = False
