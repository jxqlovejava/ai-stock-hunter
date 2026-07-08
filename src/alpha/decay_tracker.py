# -*- coding: utf-8 -*-
"""Alpha 衰减追踪器 — 监控因子 IC 衰减曲线，计算半衰期。

当因子的预测能力随时间衰减时发出预警，帮助判断因子是否「已死」。
与 alpha/schema.py 中的 AlphaDecayStatus 联动。

使用模式:
    tracker = AlphaDecayTracker()
    decay = tracker.track("pb_factor")
    if decay.is_decaying:
        print(f"因子半衰期: {decay.half_life_days:.0f} 天")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AlphaDecay:
    """单个因子的衰减状态。"""
    alpha_id: str
    half_life_days: float = 0.0             # IC 半衰期（天）
    ic_decay_curve: list[float] = field(default_factory=list)  # 滚动 IC 序列
    decay_slope: float = 0.0                # 线性衰减斜率（每月）
    is_decaying: bool = False               # 是否正在衰减
    decay_severity: str = "none"            # none / mild / moderate / severe
    last_ic: float = 0.0                    # 最新一期 IC
    peak_ic: float = 0.0                    # 历史最高 IC
    days_since_peak: int = 0               # 距峰值天数
    category: str = ""
    checked_at: datetime = field(default_factory=datetime.now)

    @property
    def summary(self) -> str:
        if self.half_life_days <= 0:
            return f"{self.alpha_id}: 无衰减数据"
        status = "⚠️ 衰减中" if self.is_decaying else "✓ 稳定"
        return (
            f"{self.alpha_id}: 半衰期={self.half_life_days:.0f}d "
            f"最新IC={self.last_ic:+.3f} 峰值IC={self.peak_ic:+.3f} "
            f"[{status}]"
        )


class AlphaDecayTracker:
    """Alpha 衰减追踪器。

    使用滚动窗口追踪因子 IC 时序，检测衰减趋势。
    基于 IC 序列的一阶差分和线性回归斜率判断衰减。
    """

    def __init__(self, min_periods: int = 12, window: int = 20):
        self._min_periods = min_periods  # 最少需要的样本数
        self._window = window             # 滚动窗口大小
        self._registry = None

    def _get_registry(self):
        """懒加载 registry，避免循环导入。"""
        if self._registry is None:
            from src.factors.registry import get_default_registry
            self._registry = get_default_registry()
        return self._registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(self, alpha_id: str, ic_series: Optional[list[float]] = None) -> AlphaDecay:
        """追踪单个因子的衰减。

        Args:
            alpha_id: 因子 ID
            ic_series: 手动传入的 IC 序列；None 则从 backtest 结果获取

        Returns:
            AlphaDecay
        """
        try:
            alpha = self._get_registry().get(alpha_id)
            category = alpha.meta.category
        except KeyError:
            category = ""

        if ic_series is None:
            # 没有 IC 历史，标记为数据不足
            return AlphaDecay(
                alpha_id=alpha_id,
                category=category,
                is_decaying=False,
                decay_severity="none",
            )

        ics = np.array(ic_series, dtype=float)
        ics = ics[~np.isnan(ics)]
        if len(ics) < self._min_periods:
            return AlphaDecay(
                alpha_id=alpha_id,
                category=category,
                is_decaying=False,
                decay_severity="none",
                last_ic=float(ics[-1]) if len(ics) > 0 else 0.0,
            )

        # 滚动 IC 均线
        n = len(ics)
        window = min(self._window, n // 2, 20)
        rolling_ic = self._rolling_mean(ics, window)

        # IC 衰减曲线 → 计算半衰期
        half_life = self._estimate_half_life(rolling_ic)

        # 线性衰减斜率
        decay_slope = self._decay_slope(rolling_ic)

        # 判定衰减状态
        peak_ic = float(np.max(rolling_ic))
        last_ic = float(rolling_ic[-1])
        peak_idx = int(np.argmax(rolling_ic))
        days_since_peak = n - peak_idx

        is_decaying, severity = self._classify_decay(
            last_ic, peak_ic, decay_slope, half_life
        )

        return AlphaDecay(
            alpha_id=alpha_id,
            half_life_days=half_life,
            ic_decay_curve=rolling_ic.tolist(),
            decay_slope=float(decay_slope),
            is_decaying=is_decaying,
            decay_severity=severity,
            last_ic=last_ic,
            peak_ic=peak_ic,
            days_since_peak=days_since_peak,
            category=category,
        )

    def track_all(
        self, ic_data: dict[str, list[float]]
    ) -> dict[str, AlphaDecay]:
        """批量追踪多个因子的衰减。

        Args:
            ic_data: {alpha_id: [ic_sequence]}

        Returns:
            {alpha_id: AlphaDecay}
        """
        results = {}
        for alpha_id, ics in ic_data.items():
            results[alpha_id] = self.track(alpha_id, ics)
        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _rolling_mean(data: np.ndarray, window: int) -> np.ndarray:
        """滚动均值，保持长度不变（前 window-1 用实际均值）。"""
        result = np.full_like(data, np.nan)
        for i in range(len(data)):
            start = max(0, i - window + 1)
            result[i] = np.mean(data[start:i + 1])
        return result

    @staticmethod
    def _decay_slope(ic_series: np.ndarray) -> float:
        """每月衰减斜率（线性回归）。"""
        n = len(ic_series)
        if n < 3:
            return 0.0
        x = np.arange(n)
        slope, _ = np.polyfit(x, ic_series, 1)
        return float(slope * 21)  # 转换为每月

    @staticmethod
    def _estimate_half_life(ic_series: np.ndarray) -> float:
        """从 IC 序列估算半衰期（天）。

        方法：找 IC 从峰值下降到一半所需的时间。
        """
        n = len(ic_series)
        if n < 3:
            return 0.0

        peak_val = np.max(ic_series)
        if peak_val <= 0:
            return 0.0

        half_val = peak_val / 2.0
        peak_idx = int(np.argmax(ic_series))

        # 从峰值往后找第一个低于 half_val 的点
        for i in range(peak_idx, n):
            if ic_series[i] <= half_val:
                return float((i - peak_idx) * 21)  # 每期 ~21 天

        # 还没降到一半，估算
        if ic_series[-1] < peak_val:
            drop_ratio = (peak_val - ic_series[-1]) / peak_val
            if drop_ratio > 0:
                return float((n - peak_idx) * 21 / drop_ratio * 0.5)

        return float(n * 21)  # 全程未衰减半，返回最长观察期

    @staticmethod
    def _classify_decay(
        last_ic: float,
        peak_ic: float,
        slope: float,
        half_life: float,
    ) -> tuple[bool, str]:
        """判定衰减严重程度。"""
        if peak_ic <= 0:
            return False, "none"

        drop_ratio = (peak_ic - last_ic) / peak_ic if peak_ic > 0 else 0.0

        if half_life > 0 and half_life < 90:
            # 半衰期 < 3 个月 → 严重衰减
            if drop_ratio > 0.5:
                return True, "severe"
            return True, "moderate"
        elif slope < -0.005:
            # 月衰减 > 0.5% IC
            if drop_ratio > 0.3:
                return True, "moderate"
            return True, "mild"
        elif drop_ratio > 0.4:
            return True, "mild"

        return False, "none"
