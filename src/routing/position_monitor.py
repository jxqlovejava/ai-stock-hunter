# -*- coding: utf-8 -*-
"""持仓持续跟踪 (PositionMonitor)。

A股本土化强化 — 区分"长期持有"和"买了不动"。
定期检查持仓的买入逻辑是否仍然成立，触发重新评估。

检查维度:
  1. 买入逻辑是否仍然成立
  2. 基本面是否恶化
  3. 宏观象限是否变化
  4. 操纵风险是否上升
  5. 是否需要触发重新评估
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class MonitorAction(str, Enum):
    HOLD = "hold"               # 继续持有，买入逻辑仍然成立
    REVIEW = "review"           # 触发重新评估
    REDUCE = "reduce"           # 建议减仓
    EXIT = "exit"               # 建议清仓离场


class TriggerReason(str, Enum):
    FUNDAMENTAL_DETERIORATION = "fundamental_deterioration"   # 基本面恶化
    MACRO_REGIME_CHANGE = "macro_regime_change"              # 宏观象限切换
    MANIPULATION_RISK_SPIKE = "manipulation_risk_spike"     # 操纵风险飙升
    VALUATION_EXTREME = "valuation_extreme"                  # 估值极端
    THESIS_BROKEN = "thesis_broken"                          # 买入逻辑被打破
    SENTIMENT_EXTREME = "sentiment_extreme"                  # 情绪极端
    TIME_BASED_REVIEW = "time_based_review"                  # 定期重评


@dataclass
class PositionSnapshot:
    """持仓快照 — 记录建仓时的关键参数用于后续对比。"""

    symbol: str
    name: str
    entry_date: datetime
    entry_price: float
    entry_score: float           # 建仓时综合评分
    entry_confidence: float      # 建仓时置信度
    entry_quadrant: str          # 建仓时宏观象限
    entry_thesis: str            # 买入逻辑描述
    entry_manipulation_risk: float = 0.0  # 建仓时操纵风险评分
    current_weight: float = 0.0


@dataclass
class MonitorResult:
    """持仓监控结果。"""

    symbol: str
    action: MonitorAction = MonitorAction.HOLD
    trigger_reasons: list[TriggerReason] = field(default_factory=list)

    # 变化追踪
    score_change: float = 0.0       # 综合评分变化
    regime_changed: bool = False    # 宏观象限是否变化
    manip_risk_change: float = 0.0  # 操纵风险变化（正=恶化）

    # 建议
    should_re_evaluate: bool = False
    recommended_action: str = ""    # 人类可读的建议描述
    urgency: str = "LOW"            # LOW / MEDIUM / HIGH / CRITICAL

    # 时间
    checked_at: datetime = field(default_factory=datetime.now)
    days_held: int = 0

    # 信号
    signals: list[str] = field(default_factory=list)


class PositionMonitor:
    """持仓持续跟踪器。

    用法:
        monitor = PositionMonitor()
        result = monitor.check(
            snapshot=PositionSnapshot(...),
            current_data={
                "score": 55, "confidence": 0.6, "quadrant": "紧货币+紧信用",
                "manipulation_risk": 75, "roe": 8.5, "sentiment": "PANIC",
            },
        )
    """

    # ── 阈值常量 ──
    SCORE_DECLINE_EXIT = 25        # 评分下降 > 25 → 建议离场
    SCORE_DECLINE_REVIEW = 15      # 评分下降 > 15 → 触发重评
    CONFIDENCE_DECLINE = 0.15      # 置信度下降 > 0.15 → 触发重评
    MANIP_SPIKE_EXIT = 50          # 操纵风险上升 > 50 → 建议离场
    MANIP_SPIKE_REVIEW = 30        # 操纵风险上升 > 30 → 触发重评
    ROE_DECLINE_EXIT = 0.30        # ROE 下降 > 30% → 基本面恶化
    REVIEW_INTERVAL_DAYS = 30      # 每 30 天强制重评一次

    def check(
        self,
        snapshot: PositionSnapshot,
        current_data: dict,
    ) -> MonitorResult:
        """检查持仓是否需要调整。

        Args:
            snapshot: 建仓时的快照
            current_data: 当前数据 {
                score, confidence, quadrant, manipulation_risk,
                roe, sentiment, current_price, sector_trend, ...
            }
        """
        result = MonitorResult(symbol=snapshot.symbol)
        result.days_held = (datetime.now() - snapshot.entry_date).days

        current_score = current_data.get("score", 50.0)
        current_confidence = current_data.get("confidence", 0.5)
        current_quadrant = current_data.get("quadrant", "")
        current_manip = current_data.get("manipulation_risk", 0.0)
        current_roe = current_data.get("roe", 0.0)

        score_delta = current_score - snapshot.entry_score
        result.score_change = score_delta
        result.manip_risk_change = current_manip - snapshot.entry_manipulation_risk

        # ── 1. 综合评分大幅下降 ──
        if score_delta < -self.SCORE_DECLINE_EXIT:
            result.trigger_reasons.append(TriggerReason.THESIS_BROKEN)
            result.action = MonitorAction.EXIT
            result.urgency = "CRITICAL"
            result.signals.append(
                f"综合评分从 {snapshot.entry_score:.0f} 降至 {current_score:.0f} "
                f"（下降 {abs(score_delta):.0f} > {self.SCORE_DECLINE_EXIT}），买入逻辑可能破裂"
            )
        elif score_delta < -self.SCORE_DECLINE_REVIEW:
            result.trigger_reasons.append(TriggerReason.TIME_BASED_REVIEW)
            result.action = MonitorAction.REVIEW
            result.urgency = "HIGH"
            result.signals.append(
                f"综合评分下降 {abs(score_delta):.0f} > {self.SCORE_DECLINE_REVIEW}，建议重新评估"
            )

        # ── 2. 宏观象限切换 ──
        if current_quadrant and current_quadrant != snapshot.entry_quadrant:
            result.regime_changed = True
            result.trigger_reasons.append(TriggerReason.MACRO_REGIME_CHANGE)

            # 判断是否是更差的象限
            regime_rank = {
                "宽货币+宽信用": 4, "宽货币+紧信用": 3,
                "紧货币+宽信用": 2, "紧货币+紧信用": 1,
            }
            old_rank = regime_rank.get(snapshot.entry_quadrant, 2)
            new_rank = regime_rank.get(current_quadrant, 2)

            if new_rank < old_rank:
                result.action = MonitorAction.REDUCE
                result.urgency = "HIGH"
                result.signals.append(
                    f"宏观象限恶化: {snapshot.entry_quadrant} → {current_quadrant}，建议减仓"
                )
            else:
                result.signals.append(
                    f"宏观象限变化: {snapshot.entry_quadrant} → {current_quadrant}，注意风格切换"
                )

        # ── 3. 操纵风险飙升 ──
        if result.manip_risk_change > self.MANIP_SPIKE_EXIT:
            result.trigger_reasons.append(TriggerReason.MANIPULATION_RISK_SPIKE)
            result.action = MonitorAction.EXIT
            result.urgency = "CRITICAL"
            result.signals.append(
                f"操纵风险从 {snapshot.entry_manipulation_risk:.0f} 飙升至 "
                f"{current_manip:.0f}（+{result.manip_risk_change:.0f} > {self.MANIP_SPIKE_EXIT}），建议立即离场"
            )
        elif result.manip_risk_change > self.MANIP_SPIKE_REVIEW:
            result.trigger_reasons.append(TriggerReason.MANIPULATION_RISK_SPIKE)
            result.action = max(result.action, MonitorAction.REVIEW)  # 取最严重的
            result.urgency = "HIGH"
            result.signals.append(
                f"操纵风险上升 {result.manip_risk_change:.0f} > {self.MANIP_SPIKE_REVIEW}，警惕"
            )

        # ── 4. 基本面恶化 ──
        entry_roe = current_data.get("entry_roe", snapshot.entry_score)
        if entry_roe > 0 and current_roe > 0:
            roe_decline = (entry_roe - current_roe) / entry_roe
            if roe_decline > self.ROE_DECLINE_EXIT:
                result.trigger_reasons.append(TriggerReason.FUNDAMENTAL_DETERIORATION)
                result.action = MonitorAction.EXIT
                result.urgency = "CRITICAL"
                result.signals.append(
                    f"ROE 从 {entry_roe:.1f}% 降至 {current_roe:.1f}%"
                    f"（下降 {roe_decline:.0%} > {self.ROE_DECLINE_EXIT:.0%}），基本面恶化"
                )

        # ── 5. 定期强制重评 ──
        if result.days_held >= self.REVIEW_INTERVAL_DAYS and not result.trigger_reasons:
            result.trigger_reasons.append(TriggerReason.TIME_BASED_REVIEW)
            result.action = MonitorAction.REVIEW
            result.signals.append(
                f"持仓 {result.days_held} 天，触发定期重评（每 {self.REVIEW_INTERVAL_DAYS} 天）"
            )

        # ── 6. 置信度大幅下降 ──
        conf_delta = snapshot.entry_confidence - current_confidence
        if conf_delta > self.CONFIDENCE_DECLINE:
            if not result.trigger_reasons:
                result.trigger_reasons.append(TriggerReason.TIME_BASED_REVIEW)
            result.action = max(result.action, MonitorAction.REVIEW)
            result.signals.append(
                f"置信度从 {snapshot.entry_confidence:.2f} 降至 {current_confidence:.2f}"
            )

        # ── 生成建议 ──
        result.should_re_evaluate = result.action != MonitorAction.HOLD
        if result.action == MonitorAction.EXIT:
            result.recommended_action = f"仓位 {snapshot.symbol} 触发 {len(result.trigger_reasons)} 个离场信号，建议清仓"
        elif result.action == MonitorAction.REDUCE:
            result.recommended_action = f"仓位 {snapshot.symbol} 建议减仓，等待宏观/基本面信号改善"
        elif result.action == MonitorAction.REVIEW:
            result.recommended_action = f"仓位 {snapshot.symbol} 触发重评，建议重新运行全管道分析"
        else:
            result.recommended_action = f"仓位 {snapshot.symbol} 买入逻辑仍然成立，继续持有"

        result.checked_at = datetime.now()
        return result

    def batch_check(
        self,
        snapshots: list[PositionSnapshot],
        current_data_map: dict[str, dict],
    ) -> list[MonitorResult]:
        """批量检查多个持仓。

        Args:
            snapshots: 持仓快照列表
            current_data_map: {symbol: current_data_dict}
        """
        results = []
        for snap in snapshots:
            data = current_data_map.get(snap.symbol, {})
            results.append(self.check(snap, data))
        return results

    @staticmethod
    def create_snapshot(
        symbol: str,
        name: str,
        entry_price: float,
        entry_score: float,
        entry_confidence: float,
        entry_quadrant: str,
        entry_thesis: str = "",
        entry_manipulation_risk: float = 0.0,
        current_weight: float = 0.0,
    ) -> PositionSnapshot:
        """创建建仓快照。"""
        return PositionSnapshot(
            symbol=symbol,
            name=name,
            entry_date=datetime.now(),
            entry_price=entry_price,
            entry_score=entry_score,
            entry_confidence=entry_confidence,
            entry_quadrant=entry_quadrant,
            entry_thesis=entry_thesis,
            entry_manipulation_risk=entry_manipulation_risk,
            current_weight=current_weight,
        )
