# -*- coding: utf-8 -*-
"""策略撤回机制 — 版本回退 + 状态重置。

支持:
  1. 实战中策略回退到历史版本
  2. 撤回模拟盘中的策略
  3. 回退记录持久化

用法:
    rollback = RollbackManager(lifecycle_manager, strategy_registry)
    record = rollback.rollback_to_previous("lc_abc123", reason="最大回撤超标")
    record = rollback.rollback_to_version("lc_abc123", version="1.0.0")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from .schema import LifecycleState, RollbackRecord, TransitionRequest

logger = logging.getLogger(__name__)


class RollbackManager:
    """策略撤回管理器。

    回退策略到历史版本，同时更新生命周期状态。
    所有回退操作记录到持久化存储。

    用法:
        rollback = RollbackManager(manager, registry)
        record = rollback.rollback("lc_abc123", reason="表现不佳")
    """

    def __init__(
        self,
        lifecycle_manager: Any = None,  # LifecycleManager
        strategy_registry: Any = None,  # StrategyRegistry
        db_path: str = "data/evolution_rollbacks.json",
    ):
        self._manager = lifecycle_manager
        self._registry = strategy_registry
        self._path = db_path
        self._records: list[RollbackRecord] = []
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rollback(
        self,
        lifecycle_id: str,
        reason: str = "",
        to_version: str = "",
    ) -> Optional[RollbackRecord]:
        """撤回策略到前一个版本或指定版本。

        Args:
            lifecycle_id: 策略生命周期 ID
            reason: 撤回原因
            to_version: 目标版本号（空=回退到前一个版本）

        Returns:
            RollbackRecord
        """
        if self._manager is None:
            logger.error("LifecycleManager 未设置")
            return None

        lc = self._manager.get(lifecycle_id)
        if lc is None:
            logger.error("生命周期 %s 不存在", lifecycle_id)
            return None

        # 检查是否可撤回
        if lc.state not in (LifecycleState.ACTIVE, LifecycleState.TRIAL, LifecycleState.DEGRADED):
            logger.warning(
                "生命周期 %s 状态为 %s，无需撤回",
                lifecycle_id, lc.state.value,
            )
            return None

        current_version = lc.strategy_version

        # 确定目标版本
        if not to_version and self._registry is not None:
            history = self._registry.history(lc.strategy_name)
            if len(history) >= 2:
                # 回退到前一版本
                to_version = history[-2].version
            else:
                logger.warning("策略 %s 无历史版本可回退", lc.strategy_name)
                return None
        elif not to_version:
            to_version = "0.0.0"  # 恢复默认

        # 收集撤回前指标
        metrics_before = {
            "sharpe": lc.live_sharpe or lc.trial_sharpe or 0,
            "return": lc.live_return or lc.trial_return or 0,
            "max_dd": lc.live_max_dd or lc.trial_max_dd or 0,
        }

        # 创建撤回记录
        record = RollbackRecord(
            lifecycle_id=lifecycle_id,
            from_version=current_version,
            to_version=to_version,
            reason=reason,
            metrics_before_rollback=metrics_before,
        )

        # 更新生命周期
        if lc.state == LifecycleState.ACTIVE:
            # 实战中撤回 → 退役
            new_state = LifecycleState.RETIRED
            reason_full = f"实战撤回: {reason} (回退到 {to_version})"
        elif lc.state == LifecycleState.DEGRADED:
            new_state = LifecycleState.RETIRED
            reason_full = f"降级撤回: {reason} (回退到 {to_version})"
        else:
            new_state = LifecycleState.CANDIDATE
            reason_full = f"撤回模拟盘: {reason} (回退到 {to_version})"

        resp = self._manager.transition(TransitionRequest(
            lifecycle_id=lifecycle_id,
            target_state=new_state,
            reason=reason_full,
            triggered_by="rollback",
        ))

        if resp.result.value != "ok":
            logger.error("撤回状态转换失败: %s", resp.message)
            return None

        # 更新策略版本
        lc.strategy_version = to_version
        self._manager._save()

        self._records.append(record)
        self._save()

        logger.info(
            "策略撤回: %s (%s → %s): %s",
            lc.strategy_name, current_version, to_version, reason,
        )
        return record

    def rollback_to_candidate(self, lifecycle_id: str, reason: str = "") -> Optional[RollbackRecord]:
        """将策略退回到候选池（TRIAL/DEGRADED → CANDIDATE）。"""
        if self._manager is None:
            return None

        lc = self._manager.get(lifecycle_id)
        if lc is None:
            return None

        record = RollbackRecord(
            lifecycle_id=lifecycle_id,
            from_version=lc.strategy_version,
            to_version=lc.strategy_version,
            reason=reason or "退回候选池",
        )

        resp = self._manager.transition(TransitionRequest(
            lifecycle_id=lifecycle_id,
            target_state=LifecycleState.CANDIDATE,
            reason=reason or "退回候选池重新优化",
            triggered_by="rollback",
        ))

        if resp.result.value != "ok":
            logger.error("退回候选池失败: %s", resp.message)
            return None

        self._records.append(record)
        self._save()
        return record

    def retire(self, lifecycle_id: str, reason: str = "") -> Optional[RollbackRecord]:
        """彻底退役策略 (→ RETIRED 终态)。"""
        if self._manager is None:
            return None

        lc = self._manager.get(lifecycle_id)
        if lc is None:
            return None

        record = RollbackRecord(
            lifecycle_id=lifecycle_id,
            from_version=lc.strategy_version,
            to_version="",
            reason=reason or "退役",
        )

        resp = self._manager.transition(TransitionRequest(
            lifecycle_id=lifecycle_id,
            target_state=LifecycleState.RETIRED,
            reason=reason or "用户手动退役",
            triggered_by="rollback",
        ))

        if resp.result.value != "ok":
            logger.error("退役失败: %s", resp.message)
            return None

        self._records.append(record)
        self._save()
        return record

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def history(self, lifecycle_id: str = "") -> list[RollbackRecord]:
        """获取撤回记录。"""
        if lifecycle_id:
            return [r for r in self._records if r.lifecycle_id == lifecycle_id]
        return list(self._records)

    def count(self) -> int:
        return len(self._records)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self):
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        data = [
            {
                "id": r.id,
                "lifecycle_id": r.lifecycle_id,
                "from_version": r.from_version,
                "to_version": r.to_version,
                "reason": r.reason,
                "metrics_before_rollback": r.metrics_before_rollback,
                "rolled_back_at": r.rolled_back_at,
            }
            for r in self._records
        ]
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._records = [
            RollbackRecord(
                id=r.get("id", ""),
                lifecycle_id=r["lifecycle_id"],
                from_version=r["from_version"],
                to_version=r["to_version"],
                reason=r.get("reason", ""),
                metrics_before_rollback=r.get("metrics_before_rollback", {}),
                rolled_back_at=r.get("rolled_back_at", ""),
            )
            for r in data
        ]
