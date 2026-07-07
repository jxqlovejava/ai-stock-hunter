# -*- coding: utf-8 -*-
"""Alpha 衰减监控器 — 跟踪 Alpha 信号从发现到失效的生命周期。

回答：「这个 Alpha 还剩多少？拥挤了吗？什么时候该退？」

核心理念：
  - 所有 Alpha 终将衰减 — 市场会学习、信息会扩散、机会会被套利
  - 监控三件事：衰减速度、拥挤度、叙事阶段迁移
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .schema import (
    AlphaDecayStatus,
    AlphaProfile,
    NarrativeLifecycle,
)

logger = logging.getLogger(__name__)


@dataclass
class AlphaSignalRecord:
    """Alpha 信号追踪记录。"""
    symbol: str
    alpha_score: float
    detected_at: datetime
    last_checked: datetime
    decay_status: AlphaDecayStatus = AlphaDecayStatus.FRESH
    narrative_stage: NarrativeLifecycle = NarrativeLifecycle.DORMANT
    peak_alpha_score: float = 0.0
    days_to_peak: int = 0
    days_from_peak_to_decay: int = 0
    history: list[tuple[datetime, float]] = field(default_factory=list)


class AlphaMonitor:
    """Alpha 衰减监控器。

    用法:
        monitor = AlphaMonitor()
        monitor.track("600519", profile)

        # 几周后检查
        decay = monitor.check("600519")
        if decay.is_crowded:
            print("Alpha 已被拥挤挤出，建议减仓")
    """

    def __init__(self):
        self._signals: dict[str, AlphaSignalRecord] = {}

    def track(self, symbol: str, profile: AlphaProfile) -> AlphaSignalRecord:
        """记录或更新 Alpha 信号。

        首次记录：创建新 SignalRecord。
        再次记录：更新历史、检测衰减。
        """
        now = datetime.now()

        if symbol in self._signals:
            record = self._signals[symbol]
            record.last_checked = now
            record.alpha_score = profile.alpha_score
            record.decay_status = profile.decay_status
            record.narrative_stage = profile.narrative.stage
            record.history.append((now, profile.alpha_score))

            # Track peak
            if profile.alpha_score > record.peak_alpha_score:
                record.peak_alpha_score = profile.alpha_score
                record.days_to_peak = (now - record.detected_at).days
        else:
            record = AlphaSignalRecord(
                symbol=symbol,
                alpha_score=profile.alpha_score,
                detected_at=now,
                last_checked=now,
                decay_status=AlphaDecayStatus.FRESH,
                narrative_stage=profile.narrative.stage,
                peak_alpha_score=profile.alpha_score,
                history=[(now, profile.alpha_score)],
            )
            self._signals[symbol] = record

        # Calculate decay timing
        if record.peak_alpha_score > 0 and record.alpha_score < record.peak_alpha_score:
            record.days_from_peak_to_decay = (
                now - record.detected_at
            ).days - record.days_to_peak

        logger.info(
            "Alpha signal tracked: %s score=%.0f status=%s stage=%s",
            symbol,
            profile.alpha_score,
            record.decay_status.value,
            record.narrative_stage.value,
        )
        return record

    def check(
        self,
        symbol: str,
        current_profile: Optional[AlphaProfile] = None,
    ) -> AlphaDecayStatus:
        """检查 Alpha 衰减状态。

        Args:
            symbol: 股票代码
            current_profile: 当前 AlphaProfile（如有则更新后检查）

        Returns:
            当前衰减状态
        """
        if current_profile:
            self.track(symbol, current_profile)

        record = self._signals.get(symbol)
        if record is None:
            return AlphaDecayStatus.FRESH

        return record.decay_status

    def detect_crowding(
        self,
        symbol: str,
        discussion_volume: float,
        discussion_growth_rate: float,
        retail_attention: float,
        institutional_attention: float,
    ) -> tuple[bool, str]:
        """检测 Alpha 是否正在被拥挤挤出。

        拥挤信号:
          1. 讨论量暴涨但逻辑无更新
          2. 散户关注度飙升而机构在撤退
          3. 叙事从 EMERGING/SPREADING 快速跳入 CONSENSUS/CROWDED

        Returns:
            (is_crowded, warning_message)
        """
        record = self._signals.get(symbol)
        warnings: list[str] = []

        # 1. 讨论量暴涨检查
        if discussion_volume > 70 and discussion_growth_rate > 20:
            warnings.append(
                f"讨论量暴涨 ({discussion_volume:.0f}, +{discussion_growth_rate:.0f}%), "
                "关注是否有新逻辑支撑，否则可能是拥挤信号"
            )

        # 2. 散户 vs 机构背离
        if retail_attention > 60 and institutional_attention < 30:
            warnings.append(
                f"散户关注度高 ({retail_attention:.0f}) 但机构关注度低 "
                f"({institutional_attention:.0f})，可能是拥挤信号"
            )

        # 3. 叙事阶段迁移检查
        if record and record.narrative_stage in (
            NarrativeLifecycle.CONSENSUS,
            NarrativeLifecycle.CROWDED,
        ):
            warnings.append(
                f"叙事已进入 {record.narrative_stage.value} 阶段，"
                f"Alpha 可能已被拥挤挤出"
            )

        is_crowded = len(warnings) >= 2
        message = " | ".join(warnings) if warnings else ""

        if is_crowded:
            logger.warning("Alpha crowding detected: %s — %s", symbol, message)

        return is_crowded, message

    def get_record(self, symbol: str) -> Optional[AlphaSignalRecord]:
        """获取 Alpha 信号追踪记录。"""
        return self._signals.get(symbol)

    def list_active(
        self,
        min_score: float = 40.0,
    ) -> list[AlphaSignalRecord]:
        """列出所有活跃的 Alpha 信号（未完全衰减）。"""
        return [
            r
            for r in self._signals.values()
            if r.alpha_score >= min_score
            and r.decay_status not in (AlphaDecayStatus.GONE,)
        ]

    def list_decayed(self) -> list[AlphaSignalRecord]:
        """列出已衰减的 Alpha 信号。"""
        return [
            r
            for r in self._signals.values()
            if r.decay_status in (AlphaDecayStatus.DECAYED, AlphaDecayStatus.GONE)
        ]

    def compute_decay_velocity(
        self,
        symbol: str,
        window_days: int = 30,
    ) -> float:
        """计算 Alpha 衰减速度（日平均衰减量）。

        Returns:
            每日 Alpha 评分衰减量（正数=衰减中，0=稳定，负数=在增强）
        """
        record = self._signals.get(symbol)
        if not record or len(record.history) < 2:
            return 0.0

        cutoff = datetime.now() - timedelta(days=window_days)
        recent = [(t, s) for t, s in record.history if t >= cutoff]

        if len(recent) < 2:
            return 0.0

        recent.sort(key=lambda x: x[0])
        total_decay = recent[0][1] - recent[-1][1]
        days = max(1, (recent[-1][0] - recent[0][0]).days)

        return round(total_decay / days, 2)

    def summary(self, symbol: str) -> str:
        """生成 Alpha 监控摘要。"""
        record = self._signals.get(symbol)
        if not record:
            return f"{symbol}: 无 Alpha 信号记录"

        velocity = self.compute_decay_velocity(symbol)
        direction = (
            "衰减中" if velocity > 0.5
            else "缓慢衰减" if velocity > 0.1
            else "稳定" if velocity >= 0
            else "增强中"
        )

        return (
            f"{symbol}: Alpha {record.alpha_score:.0f}/100 "
            f"[{record.decay_status.value}] "
            f"叙事: {record.narrative_stage.value} "
            f"衰减速度: {velocity:.1f}/天 ({direction}) "
            f"已追踪 {record.days_from_peak_to_decay} 天"
        )
