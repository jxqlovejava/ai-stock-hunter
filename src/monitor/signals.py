"""Monitor 事件信号生成器.

将 MonitorStore 中的 active/triggered events 转换为分析管线可消费的信号。

Ref: ai-gold-miner signals/monitor_signal.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .models import MonitorEvent, MonitorStatus, MonitorType
from .store import MonitorStore

logger = logging.getLogger(__name__)


@dataclass
class MonitorSignal:
    """Monitor 信号 — 可被分析管线消费."""
    name: str
    dimension: str = "monitor"
    direction: str = "neutral"          # bullish / bearish / neutral
    strength: str = "moderate"          # strong / moderate / weak
    score: float = 0.0                  # -1.0 ~ +1.0
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _infer_direction_from_text(text: str) -> str:
    """从文本推断方向."""
    text_lower = text.lower()
    bullish_kw = ["利多", "看多", "加仓", "买入", "反弹", "上涨",
                   "bullish", "buy", "long", "增持"]
    bearish_kw = ["利空", "看空", "减仓", "卖出", "下跌", "回调",
                   "bearish", "sell", "short", "减持",
                   "强平", "恐慌", "出逃", "踩踏"]

    if any(kw in text_lower for kw in bearish_kw):
        return "bearish"
    if any(kw in text_lower for kw in bullish_kw):
        return "bullish"
    return "neutral"


class MonitorSignalGenerator:
    """Monitor 事件 → 信号转换器.

    两种信号类型:
    1. **触发信号**: status=triggered → 方向信号
    2. **观测信号**: status=active → 中性提醒
    """

    def __init__(self, store: MonitorStore | None = None) -> None:
        self.store = store or MonitorStore()

    def generate(self, symbol: str = "") -> list[MonitorSignal]:
        """生成所有 monitor 相关信号.

        Args:
            symbol: 股票代码，为空则返回全市场
        """
        signals: list[MonitorSignal] = []

        # 1. 已触发的 → 方向信号
        signals.extend(self._triggered_signals(symbol))

        # 2. 活跃观测中 → 中性提醒
        signals.extend(self._active_signals(symbol))

        triggered_count = sum(1 for s in signals if s.direction != "neutral")
        logger.info(
            f"[MonitorSignal] {symbol or 'ALL'}: {len(signals)}个信号 "
            f"(方向信号: {triggered_count}, 观测提醒: {len(signals) - triggered_count})"
        )
        return signals

    # ------------------------------------------------------------------
    # 已触发 monitor → 方向信号
    # ------------------------------------------------------------------

    def _triggered_signals(self, symbol: str = "") -> list[MonitorSignal]:
        """最近触发的 monitor → 方向信号."""
        triggered = self.store.get_triggered_recent(lookback_days=7)
        if symbol:
            triggered = [e for e in triggered if e.symbol == symbol]

        signals: list[MonitorSignal] = []
        now = datetime.now()

        for monitor in triggered:
            triggered_dt = self._parse_time(monitor.triggered_at)
            hours_ago = (
                (now - triggered_dt).total_seconds() / 3600
                if triggered_dt else 168  # default 7 days
            )

            # 时效性加权 (24h内权重最高)
            if hours_ago <= 24:
                weight = 1.0
                strength = "strong"
            elif hours_ago <= 72:
                weight = 0.6
                strength = "moderate"
            elif hours_ago <= 168:
                weight = 0.3
                strength = "weak"
            else:
                continue  # 超过7天不纳入

            # 方向推断
            result_text = monitor.trigger_result or monitor.trigger_condition
            direction = monitor.trigger_direction
            if direction == "neutral":
                direction = _infer_direction_from_text(result_text)

            dir_sign = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
            score = dir_sign.get(direction, 0.0) * weight

            hours_desc = (
                f"{hours_ago:.0f}h前" if hours_ago < 48
                else f"{hours_ago / 24:.0f}天前"
            )

            desc_parts = [
                f"[{hours_desc}触发]",
                f"条件: {monitor.trigger_condition[:80]}",
            ]
            if monitor.trigger_result:
                desc_parts.append(f"结果: {monitor.trigger_result[:120]}")
            if monitor.action_on_trigger:
                desc_parts.append(f"建议: {monitor.action_on_trigger[:100]}")

            signals.append(MonitorSignal(
                name=f"Monitor触发: {monitor.name}",
                dimension="monitor",
                direction=direction,
                strength=strength,
                score=round(score, 2),
                description=" | ".join(desc_parts),
                metadata={
                    "event_id": monitor.event_id,
                    "monitor_name": monitor.name,
                    "monitor_type": monitor.monitor_type.value,
                    "symbol": monitor.symbol,
                    "symbol_name": monitor.symbol_name,
                    "status": "triggered",
                    "triggered_at": monitor.triggered_at,
                    "hours_ago": round(hours_ago, 1),
                    "recency_weight": weight,
                    "severity": monitor.trigger_severity,
                    "action": monitor.action_on_trigger,
                },
            ))

        signals.sort(key=lambda s: s.metadata.get("hours_ago", 999))
        return signals

    # ------------------------------------------------------------------
    # 活跃 monitor → 中性观测提醒
    # ------------------------------------------------------------------

    def _active_signals(self, symbol: str = "") -> list[MonitorSignal]:
        """活跃 monitor → 中性观测信号."""
        active = self.store.get_active()
        if symbol:
            active = [e for e in active if e.symbol == symbol]

        signals: list[MonitorSignal] = []
        for monitor in active:
            desc_parts = ["🔍 正在观测中"]
            if monitor.trigger_condition:
                desc_parts.append(f"条件: {monitor.trigger_condition[:80]}")
            if monitor.action_on_trigger:
                desc_parts.append(f"触发后: {monitor.action_on_trigger[:100]}")
            if monitor.age_hours > 24:
                desc_parts.append(f"(已观测 {monitor.age_hours / 24:.0f}天)")

            type_icon = {
                MonitorType.MARGIN: "💰",
                MonitorType.BLOCK_TRADE: "📦",
                MonitorType.NORTHBOUND: "🌏",
                MonitorType.TECHNICAL: "📊",
                MonitorType.SENTIMENT: "😱",
                MonitorType.PRICE_LEVEL: "🎯",
                MonitorType.DIVERGENCE_CONSENSUS: "🔄",
            }.get(monitor.monitor_type, "📌")

            signals.append(MonitorSignal(
                name=f"{type_icon} Monitor: {monitor.name}",
                dimension="monitor",
                direction="neutral",
                strength="weak",
                score=0.0,
                description=" | ".join(desc_parts),
                metadata={
                    "event_id": monitor.event_id,
                    "monitor_name": monitor.name,
                    "monitor_type": monitor.monitor_type.value,
                    "symbol": monitor.symbol,
                    "symbol_name": monitor.symbol_name,
                    "status": "active",
                    "trigger_condition": monitor.trigger_condition,
                    "action_on_trigger": monitor.action_on_trigger,
                    "check_frequency": monitor.check_frequency,
                    "age_hours": round(monitor.age_hours, 1),
                    "severity": monitor.trigger_severity,
                },
            ))

        return signals

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_time(iso_str: str | None) -> datetime | None:
        if not iso_str:
            return None
        try:
            return datetime.fromisoformat(iso_str)
        except (ValueError, TypeError):
            return None


# ── 便捷函数 ──────────────────────────────────────────────────────


def generate_monitor_signals(symbol: str = "") -> list[MonitorSignal]:
    """一行调用：从 MonitorStore 生成信号."""
    store = MonitorStore()
    gen = MonitorSignalGenerator(store)
    return gen.generate(symbol)
