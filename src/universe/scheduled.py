# -*- coding: utf-8 -*-
"""ScheduledUniverseSelectionModel — 定时选股模型。

按预设频率 (每日/每周/每月) 执行一次选股逻辑，
在两次重平衡之间返回缓存的股票列表。

适用于：
- 需要定期刷新选股池但不想每 tick 都重新计算的场景。
- 配合外部定时任务 (cron / scheduler) 使用。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable, Optional

import pandas as pd

from .base import UniverseSelectionModel

logger = logging.getLogger(__name__)

# 频率 → timedelta 映射
_REBALANCE_DELTA: dict[str, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),  # 近似值
}


class ScheduledUniverseSelectionModel(UniverseSelectionModel):
    """定时选股模型 — 按频率执行筛选，中间返回缓存。

    内部维护一个 ``_strategy`` 函数作为实际的选股逻辑，
    并在每次重平衡时调用它。

    Parameters
    ----------
    rebalance_frequency : str
        重平衡频率: ``"daily"`` / ``"weekly"`` / ``"monthly"``。
    strategy : Callable | None
        实际的选股函数，接收 DataFrame 返回股票列表。
        如果为 None，则返回当前缓存（即什么都不做）。
    """

    def __init__(
        self,
        rebalance_frequency: str = "daily",
        strategy: Optional[Callable[[pd.DataFrame], list[str]]] = None,
    ) -> None:
        if rebalance_frequency not in _REBALANCE_DELTA:
            valid = ", ".join(_REBALANCE_DELTA)
            raise ValueError(
                f"Unknown rebalance_frequency '{rebalance_frequency}'. "
                f"Valid options: {valid}"
            )

        self.rebalance_frequency = rebalance_frequency
        self._strategy = strategy

        # 缓存
        self._cached_universe: list[str] = []
        self._last_rebalance: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_due(self) -> bool:
        """距离上次重平衡是否已达到频率间隔？"""
        if self._last_rebalance is None:
            return True
        delta = _REBALANCE_DELTA[self.rebalance_frequency]
        return datetime.now() - self._last_rebalance >= delta

    @property
    def cached_universe(self) -> list[str]:
        """返回当前缓存的股票列表 (可能是过期数据)。"""
        return list(self._cached_universe)

    def select_universe(self, data: pd.DataFrame) -> list[str]:
        """按定时频率选择股票池。

        如果距离上次重平衡已达到频率间隔，则重新执行选股；
        否则直接返回缓存结果。

        Args:
            data: 传递给 ``strategy`` 的原始数据 (格式由 strategy 约定)。

        Returns:
            当前选股池的股票代码列表。
        """
        if self.is_due and self._strategy is not None:
            try:
                selected = self._strategy(data)
                self._cached_universe = list(selected) if selected else []
                self._last_rebalance = datetime.now()
                logger.info(
                    "ScheduledUniverse rebalanced (%s): %d symbols",
                    self.rebalance_frequency, len(self._cached_universe),
                )
            except Exception:
                logger.exception(
                    "ScheduledUniverse strategy failed on rebalance — "
                    "falling back to cached universe (%d symbols)",
                    len(self._cached_universe),
                )
                # 策略执行失败时保留旧缓存
        else:
            reason = "not due" if not self.is_due else "no strategy set"
            logger.debug("ScheduledUniverse skipped rebalance (%s)", reason)

        return self.cached_universe

    def force_rebalance(self, data: pd.DataFrame) -> list[str]:
        """强制立即重平衡，忽略定时逻辑。

        Returns:
            重新计算后的股票池列表。
        """
        if self._strategy is None:
            logger.warning("force_rebalance called but no strategy is set")
            return self.cached_universe

        selected = self._strategy(data)
        self._cached_universe = list(selected) if selected else []
        self._last_rebalance = datetime.now()
        logger.info("ScheduledUniverse force-rebalanced: %d symbols", len(self._cached_universe))
        return self.cached_universe

    def clear_cache(self) -> None:
        """清空缓存状态，下次 ``select_universe`` 将强制重选。"""
        self._cached_universe = []
        self._last_rebalance = None

    @property
    def days_since_rebalance(self) -> Optional[float]:
        """距离上次重平衡的天数。从未重平衡则返回 None。"""
        if self._last_rebalance is None:
            return None
        return (datetime.now() - self._last_rebalance).total_seconds() / 86400.0

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(frequency={self.rebalance_frequency}, "
            f"cached={len(self._cached_universe)} symbols, "
            f"strategy={'set' if self._strategy else 'none'})"
        )
