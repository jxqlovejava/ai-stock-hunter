# -*- coding: utf-8 -*-
"""模拟盘运行器 — 将候选策略接入模拟交易，自动下单跟踪。

职责:
  1. 从 CANDIDATE 状态启动模拟盘
  2. 桥接 PaperTradingBridge 执行交易信号
  3. 记录模拟盘关键指标
  4. 达到结束条件时通知 LifecycleManager

用法:
    runner = TrialRunner(lifecycle_manager, config)
    runner.start_trial(lifecycle_id)
    # 后台定期调用:
    runner.tick()  # 同步账户，更新指标
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .schema import (
    EvolutionConfig,
    LifecycleState,
    StrategyLifecycle,
    TrialMetrics,
    TrialThresholds,
)

logger = logging.getLogger(__name__)


@dataclass
class TrialSession:
    """一次模拟盘会话状态。"""
    lifecycle_id: str = ""
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_tick_at: str = ""
    total_return: float = 0.0
    max_drawdown: float = 0.0
    peak_value: float = 0.0
    current_drawdown: float = 0.0
    trades_executed: int = 0
    running_days: int = 0
    is_active: bool = True
    error_count: int = 0
    last_error: str = ""


class TrialRunner:
    """模拟盘自动运行器。

    从 CANDIDATE 状态启动 → 连接 PaperTradingBridge → 自动执行信号。

    用法:
        runner = TrialRunner(manager, config)
        runner.start_trial("lc_abc123")
        # 每日 tick
        metrics = runner.tick("lc_abc123")
        if metrics and runner.check_conditions("lc_abc123"):
            # 达标, 可进入 active
            ...
    """

    def __init__(
        self,
        lifecycle_manager: Any = None,  # LifecycleManager
        config: Optional[EvolutionConfig] = None,
    ):
        self._manager = lifecycle_manager
        self._config = config or EvolutionConfig()
        self._sessions: dict[str, TrialSession] = {}
        self._bridge = None  # 延迟导入

    @property
    def bridge(self):
        """懒加载 PaperTradingBridge。"""
        if self._bridge is None:
            try:
                from src.paper_trading.bridge import PaperTradingBridge
                self._bridge = PaperTradingBridge()
            except ImportError as e:
                logger.warning("PaperTradingBridge 不可用: %s", e)
                self._bridge = None
        return self._bridge

    @property
    def thresholds(self) -> TrialThresholds:
        return self._config.trial

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_trial(self, lifecycle_id: str, capital: float = 100_000.0) -> bool:
        """启动模拟盘试验。

        Args:
            lifecycle_id: 策略生命周期 ID
            capital: 初始资金

        Returns:
            是否成功启动
        """
        if self._manager is None:
            logger.error("LifecycleManager 未设置，无法启动模拟盘")
            return False

        lc = self._manager.get(lifecycle_id)
        if lc is None:
            logger.error("生命周期 %s 不存在", lifecycle_id)
            return False

        if lc.state != LifecycleState.CANDIDATE:
            logger.warning(
                "生命周期 %s 状态为 %s，无法启动模拟盘 (需为 CANDIDATE)",
                lifecycle_id, lc.state.value,
            )
            return False

        # 转换为 TRIAL
        from .schema import TransitionRequest, LifecycleState as LS
        resp = self._manager.transition(TransitionRequest(
            lifecycle_id=lifecycle_id,
            target_state=LS.TRIAL,
            reason=f"启动模拟盘试验 (初始资金 {capital:,.0f})",
            triggered_by="trial_runner",
        ))
        if resp.result.value != "ok":
            logger.error("状态转换失败: %s", resp.message)
            return False

        # 创建会话
        session = TrialSession(lifecycle_id=lifecycle_id)
        self._sessions[lifecycle_id] = session

        # 更新生命周期
        lc.trial_started_at = session.started_at
        self._manager._save()

        logger.info("模拟盘启动: %s (%s)", lc.strategy_name, lifecycle_id)
        return True

    def stop_trial(self, lifecycle_id: str, reason: str = "手动停止"):
        """停止模拟盘试验。"""
        session = self._sessions.get(lifecycle_id)
        if session:
            session.is_active = False

        if self._manager:
            lc = self._manager.get(lifecycle_id)
            if lc:
                lc.trial_ended_at = datetime.now().isoformat()
                self._manager._save()

        logger.info("模拟盘停止: %s — %s", lifecycle_id, reason)

    def pause_trial(self, lifecycle_id: str, reason: str = "手动暂停"):
        """暂停模拟盘（不下单但继续跟踪）。"""
        session = self._sessions.get(lifecycle_id)
        if session:
            session.is_active = False
        logger.info("模拟盘暂停: %s — %s", lifecycle_id, reason)

    def resume_trial(self, lifecycle_id: str):
        """恢复模拟盘。"""
        session = self._sessions.get(lifecycle_id)
        if session:
            session.is_active = True
        logger.info("模拟盘恢复: %s", lifecycle_id)

    def tick(self, lifecycle_id: str) -> Optional[TrialMetrics]:
        """执行一次检查周期 — 同步账户状态并更新指标。

        应定期调用（如每日）。
        """
        session = self._sessions.get(lifecycle_id)
        if session is None:
            logger.warning("无活动会话: %s", lifecycle_id)
            return None

        if not session.is_active:
            return None

        session.last_tick_at = datetime.now().isoformat()
        session.running_days += 1

        # 同步模拟账户
        metrics = self._calculate_metrics(lifecycle_id)
        session.total_return = metrics.total_return
        session.current_drawdown = abs(metrics.max_drawdown)
        session.max_drawdown = max(session.max_drawdown, abs(metrics.max_drawdown))
        session.trades_executed = metrics.total_trades

        # 更新 lifecycle
        if self._manager:
            self._manager.update_trial_metrics(
                lifecycle_id=lifecycle_id,
                sharpe=metrics.sharpe_ratio,
                total_return=metrics.total_return,
                max_dd=metrics.max_drawdown,
                trades=metrics.total_trades,
            )

        return metrics

    def check_conditions(self, lifecycle_id: str) -> tuple[bool, str]:
        """检查模拟盘是否达标。

        Returns:
            (是否达标, 说明)
        """
        session = self._sessions.get(lifecycle_id)
        if session is None:
            return False, "无活动会话"

        t = self.thresholds
        checks = []

        if session.running_days < t.min_duration_days:
            checks.append(
                f"运行天数 {session.running_days}/{t.min_duration_days}"
            )

        if session.trades_executed < t.min_trades:
            checks.append(
                f"交易笔数 {session.trades_executed}/{t.min_trades}"
            )

        if session.max_drawdown > t.max_drawdown_limit:
            return False, f"最大回撤 {session.max_drawdown:.1%} 超标 (>{t.max_drawdown_limit:.0%})"

        if checks:
            return False, "; ".join(checks)

        # 所有基本条件满足
        return True, "模拟盘指标达标"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _calculate_metrics(self, lifecycle_id: str) -> TrialMetrics:
        """从模拟账户同步并计算指标。"""
        metrics = TrialMetrics(lifecycle_id=lifecycle_id)

        # 尝试从 PaperTradingBridge 获取
        if self.bridge:
            try:
                session = self.bridge.sync()
                if session:
                    metrics.total_return = (
                        (session.total_assets - session.initial_capital)
                        / session.initial_capital
                    ) if session.initial_capital > 0 else 0
                    metrics.total_trades = session.orders_today
                    # 简化 Sharpe 计算
                    if metrics.total_return > 0 and metrics.running_days > 0:
                        metrics.annualized_return = (
                            (1 + metrics.total_return) ** (252 / max(1, metrics.running_days)) - 1
                        )
                        metrics.sharpe_ratio = (
                            metrics.annualized_return / max(0.01, abs(metrics.max_drawdown))
                        ) * 0.5  # 简化估算
                    return metrics
            except Exception as e:
                logger.warning("同步模拟账户失败: %s", e)

        # 回退 — 使用存储的指标
        if self._manager:
            lc = self._manager.get(lifecycle_id)
            if lc:
                metrics.total_return = lc.trial_return or 0.0
                metrics.max_drawdown = lc.trial_max_dd or 0.0
                metrics.sharpe_ratio = lc.trial_sharpe or 0.0
                metrics.total_trades = lc.trial_trades

        session = self._sessions.get(lifecycle_id)
        if session:
            metrics.running_days = session.running_days

        return metrics

    def get_active_sessions(self) -> list[TrialSession]:
        """列出所有活跃的模拟盘会话。"""
        return [s for s in self._sessions.values() if s.is_active]

    def summary(self) -> str:
        """生成模拟盘摘要。"""
        active = self.get_active_sessions()
        if not active:
            return "📭 无活跃模拟盘会话"

        lines = [f"🧪 模拟盘运行中: {len(active)} 个"]
        for s in active:
            name = ""
            if self._manager:
                lc = self._manager.get(s.lifecycle_id)
                if lc:
                    name = lc.strategy_name
            lines.append(
                f"  • {name or s.lifecycle_id} | "
                f"{s.running_days}天 | "
                f"收益 {s.total_return:+.1%} | "
                f"最大回撤 {s.max_drawdown:.1%} | "
                f"交易 {s.trades_executed}笔"
            )
        return "\n".join(lines)
