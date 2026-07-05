# -*- coding: utf-8 -*-
"""策略生命周期管理器 — 状态机引擎 + 持久化。

管理策略从 EXTRACTED → CANDIDATE → TRIAL → ACTIVE → RETIRED 的完整生命周期。
所有状态变更都经过验证和记录。

用法:
    manager = LifecycleManager()

    # 创建生命周期
    lc = manager.create(paper_id="abc123", strategy_name="MVP_FamaFrench")

    # 状态转换
    resp = manager.transition(TransitionRequest(
        lifecycle_id=lc.id,
        target_state=LifecycleState.CANDIDATE,
        reason="回测通过: Sharpe 1.2",
    ))

    # 查询
    active = manager.list_by_state(LifecycleState.ACTIVE)
    history = manager.history(lc.id)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from .schema import (
    LifecycleState,
    StateTransition,
    StrategyLifecycle,
    TransitionRequest,
    TransitionResponse,
    TransitionResult,
    STATE_TRANSITIONS,
)

logger = logging.getLogger(__name__)


class LifecycleManager:
    """策略生命周期管理器。

    职责:
      1. 状态机验证 — 确保只能进行合法转换
      2. 条件检查 — 转换前检查前置条件
      3. 历史记录 — 每次转换记录到 state_history
      4. 持久化 — JSON 文件存储

    用法:
        manager = LifecycleManager("data/evolution_lifecycles.json")
        lc = manager.create(paper_id="p1", strategy_name="test")
        resp = manager.transition(TransitionRequest(
            lifecycle_id=lc.id,
            target_state=LifecycleState.CANDIDATE,
        ))
    """

    def __init__(self, db_path: str = "data/evolution_lifecycles.json"):
        self._path = db_path
        self._memory_only = db_path == ":memory:"
        self._lifecycles: dict[str, StrategyLifecycle] = {}
        if not self._memory_only:
            self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        paper_id: str = "",
        strategy_name: str = "",
        strategy_version: str = "",
        state: LifecycleState = LifecycleState.EXTRACTED,
    ) -> StrategyLifecycle:
        """创建新的策略生命周期。

        Args:
            paper_id: 关联的论文 ID
            strategy_name: 策略名称
            strategy_version: 策略版本号
            state: 初始状态

        Returns:
            StrategyLifecycle
        """
        lc = StrategyLifecycle(
            paper_id=paper_id,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            state=state,
        )
        # 记录初始状态
        lc.state_history.append(StateTransition(
            from_state=state,
            to_state=state,
            reason="初始化",
            triggered_by="system",
        ))
        self._lifecycles[lc.id] = lc
        self._save()
        logger.info("生命周期 %s 创建: %s (%s)", lc.id, strategy_name, state.value)
        return lc

    def get(self, lifecycle_id: str) -> Optional[StrategyLifecycle]:
        """获取生命周期。"""
        return self._lifecycles.get(lifecycle_id)

    def get_by_strategy(self, strategy_name: str) -> Optional[StrategyLifecycle]:
        """按策略名查找。"""
        for lc in self._lifecycles.values():
            if lc.strategy_name == strategy_name:
                return lc
        return None

    def list_all(self) -> list[StrategyLifecycle]:
        """列出所有生命周期。"""
        return list(self._lifecycles.values())

    def list_by_state(self, state: LifecycleState) -> list[StrategyLifecycle]:
        """按状态筛选。"""
        return [lc for lc in self._lifecycles.values() if lc.state == state]

    def list_active_or_trial(self) -> list[StrategyLifecycle]:
        """列出实战中或试验中的策略。"""
        return [
            lc for lc in self._lifecycles.values()
            if lc.state in (LifecycleState.ACTIVE, LifecycleState.TRIAL)
        ]

    def delete(self, lifecycle_id: str) -> bool:
        """删除生命周期记录。"""
        if lifecycle_id in self._lifecycles:
            del self._lifecycles[lifecycle_id]
            self._save()
            return True
        return False

    def history(self, lifecycle_id: str) -> list[StateTransition]:
        """获取状态变更历史。"""
        lc = self.get(lifecycle_id)
        if lc is None:
            return []
        return list(lc.state_history)

    # ------------------------------------------------------------------
    # State Machine
    # ------------------------------------------------------------------

    def transition(self, request: TransitionRequest) -> TransitionResponse:
        """执行状态转换。

        验证:
          1. lifecycle_id 存在
          2. 目标状态在当前状态的允许转换集合中
          3. 前置条件满足 (除非 force=True)

        Args:
            request: TransitionRequest

        Returns:
            TransitionResponse
        """
        lc = self.get(request.lifecycle_id)
        if lc is None:
            return TransitionResponse(
                request=request,
                result=TransitionResult.ERROR,
                message=f"生命周期不存在: {request.lifecycle_id}",
            )

        current = lc.state
        target = request.target_state

        # 检查是否合法转换
        allowed = STATE_TRANSITIONS.get(current, set())
        if target not in allowed and not request.force:
            return TransitionResponse(
                request=request,
                result=TransitionResult.INVALID_TRANSITION,
                message=(
                    f"不允许从 {current.value} 转换到 {target.value}。"
                    f"允许: {[s.value for s in allowed]}"
                ),
            )

        # 前置条件检查
        if not request.force:
            condition_check = self._check_preconditions(lc, target)
            if not condition_check[0]:
                return TransitionResponse(
                    request=request,
                    result=TransitionResult.CONDITION_NOT_MET,
                    message=condition_check[1],
                )

        # 执行转换
        transition = StateTransition(
            from_state=current,
            to_state=target,
            reason=request.reason,
            triggered_by=request.triggered_by,
        )
        lc.state = target
        lc.state_history.append(transition)
        lc.updated_at = datetime.now().isoformat()

        self._save()

        logger.info(
            "生命周期 %s: %s → %s (%s)",
            request.lifecycle_id, current.value, target.value, request.reason,
        )
        return TransitionResponse(
            request=request,
            result=TransitionResult.OK,
            message=f"{current.value} → {target.value}",
            new_state=target,
        )

    def can_transition(
        self, lifecycle_id: str, target: LifecycleState
    ) -> tuple[bool, str]:
        """检查是否可以执行转换（不实际执行）。"""
        lc = self.get(lifecycle_id)
        if lc is None:
            return False, f"生命周期不存在: {lifecycle_id}"

        allowed = STATE_TRANSITIONS.get(lc.state, set())
        if target not in allowed:
            return False, (
                f"不允许从 {lc.state.value} 转换到 {target.value}。"
                f"允许: {[s.value for s in allowed]}"
            )

        return self._check_preconditions(lc, target)

    # ------------------------------------------------------------------
    # Update Methods
    # ------------------------------------------------------------------

    def update_backtest_result(
        self,
        lifecycle_id: str,
        sharpe: float,
        total_return: float,
        max_dd: float,
        passed: bool,
    ):
        """更新回测结果。"""
        lc = self.get(lifecycle_id)
        if lc is None:
            return
        lc.backtest_sharpe = sharpe
        lc.backtest_return = total_return
        lc.backtest_max_dd = max_dd
        lc.backtest_passed = passed
        lc.backtest_run_at = datetime.now().isoformat()
        lc.updated_at = datetime.now().isoformat()
        self._save()

    def update_trial_metrics(
        self,
        lifecycle_id: str,
        sharpe: float,
        total_return: float,
        max_dd: float,
        trades: int,
        passed: bool = False,
    ):
        """更新模拟盘指标。"""
        lc = self.get(lifecycle_id)
        if lc is None:
            return
        lc.trial_sharpe = sharpe
        lc.trial_return = total_return
        lc.trial_max_dd = max_dd
        lc.trial_trades = trades
        lc.trial_passed = passed
        lc.updated_at = datetime.now().isoformat()
        self._save()

    def update_live_metrics(
        self,
        lifecycle_id: str,
        sharpe: float,
        total_return: float,
        max_dd: float,
    ):
        """更新实战指标。"""
        lc = self.get(lifecycle_id)
        if lc is None:
            return
        lc.live_sharpe = sharpe
        lc.live_return = total_return
        lc.live_max_dd = max_dd
        lc.updated_at = datetime.now().isoformat()
        self._save()

    # ------------------------------------------------------------------
    # Precondition Checks
    # ------------------------------------------------------------------

    def _check_preconditions(
        self, lc: StrategyLifecycle, target: LifecycleState
    ) -> tuple[bool, str]:
        """检查状态转换的前置条件。"""
        if target == LifecycleState.CANDIDATE:
            if not lc.backtest_passed:
                return False, "回测未通过，无法进入候选池"
            return True, ""

        if target == LifecycleState.TRIAL:
            if lc.state == LifecycleState.CANDIDATE and not lc.backtest_passed:
                return False, "回测未通过，无法进入模拟盘"
            return True, ""

        if target == LifecycleState.ACTIVE:
            if not lc.trial_passed:
                return False, "模拟盘未达标，无法进入实战"
            return True, ""

        if target == LifecycleState.OPTIMIZING:
            if lc.state != LifecycleState.DEGRADED:
                return False, "仅 DEGRADED 状态可触发自动优化"
            return True, ""

        return True, ""

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self):
        if self._memory_only:
            return
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        data = {}
        for lc_id, lc in self._lifecycles.items():
            data[lc_id] = {
                "id": lc.id,
                "paper_id": lc.paper_id,
                "strategy_name": lc.strategy_name,
                "strategy_version": lc.strategy_version,
                "state": lc.state.value,
                "state_history": [
                    {
                        "from_state": t.from_state.value,
                        "to_state": t.to_state.value,
                        "reason": t.reason,
                        "triggered_by": t.triggered_by,
                        "metrics_snapshot": t.metrics_snapshot,
                        "timestamp": t.timestamp,
                    }
                    for t in lc.state_history
                ],
                "backtest_sharpe": lc.backtest_sharpe,
                "backtest_return": lc.backtest_return,
                "backtest_max_dd": lc.backtest_max_dd,
                "backtest_passed": lc.backtest_passed,
                "backtest_run_at": lc.backtest_run_at,
                "trial_started_at": lc.trial_started_at,
                "trial_ended_at": lc.trial_ended_at,
                "trial_sharpe": lc.trial_sharpe,
                "trial_return": lc.trial_return,
                "trial_max_dd": lc.trial_max_dd,
                "trial_trades": lc.trial_trades,
                "trial_passed": lc.trial_passed,
                "active_started_at": lc.active_started_at,
                "live_sharpe": lc.live_sharpe,
                "live_return": lc.live_return,
                "live_max_dd": lc.live_max_dd,
                "created_at": lc.created_at,
                "updated_at": lc.updated_at,
                "error_message": lc.error_message,
                "notes": lc.notes,
            }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for lc_id, raw in data.items():
            lc = StrategyLifecycle(
                id=raw.get("id", lc_id),
                paper_id=raw.get("paper_id", ""),
                strategy_name=raw.get("strategy_name", ""),
                strategy_version=raw.get("strategy_version", ""),
                state=LifecycleState(raw.get("state", "extracted")),
                state_history=[
                    StateTransition(
                        from_state=LifecycleState(t["from_state"]),
                        to_state=LifecycleState(t["to_state"]),
                        reason=t.get("reason", ""),
                        triggered_by=t.get("triggered_by", ""),
                        metrics_snapshot=t.get("metrics_snapshot", {}),
                        timestamp=t.get("timestamp", ""),
                    )
                    for t in raw.get("state_history", [])
                ],
                backtest_sharpe=raw.get("backtest_sharpe"),
                backtest_return=raw.get("backtest_return"),
                backtest_max_dd=raw.get("backtest_max_dd"),
                backtest_passed=raw.get("backtest_passed", False),
                backtest_run_at=raw.get("backtest_run_at"),
                trial_started_at=raw.get("trial_started_at"),
                trial_ended_at=raw.get("trial_ended_at"),
                trial_sharpe=raw.get("trial_sharpe"),
                trial_return=raw.get("trial_return"),
                trial_max_dd=raw.get("trial_max_dd"),
                trial_trades=raw.get("trial_trades", 0),
                trial_passed=raw.get("trial_passed", False),
                active_started_at=raw.get("active_started_at"),
                live_sharpe=raw.get("live_sharpe"),
                live_return=raw.get("live_return"),
                live_max_dd=raw.get("live_max_dd"),
                created_at=raw.get("created_at", ""),
                updated_at=raw.get("updated_at", ""),
                error_message=raw.get("error_message", ""),
                notes=raw.get("notes", ""),
            )
            self._lifecycles[lc_id] = lc

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """生成生命周期摘要。"""
        by_state: dict[str, int] = {}
        for lc in self._lifecycles.values():
            key = lc.state.value
            by_state[key] = by_state.get(key, 0) + 1

        lines = ["📊 策略生命周期摘要", f"总数: {len(self._lifecycles)}"]
        for state_name, count in sorted(by_state.items()):
            emoji = {
                "extracted": "📄", "candidate": "⭐", "trial": "🧪",
                "active": "💰", "degraded": "⚠️", "optimizing": "🔧",
                "rejected": "❌", "retired": "🏁", "error": "💥",
            }.get(state_name, "❓")
            lines.append(f"  {emoji} {state_name}: {count}")
        return "\n".join(lines)
