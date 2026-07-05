# -*- coding: utf-8 -*-
"""模拟盘监控器 — 持续监控模拟盘/实战策略表现，触发降级/优化。

职责:
  1. 定期检查所有 TRIAL/ACTIVE 策略的指标
  2. 检测性能下降 (DEGRADED 触发)
  3. 自动触发 OPTIMIZING (如配置启用)

用法:
    monitor = TrialMonitor(lifecycle_manager, trial_runner, config)
    alerts = monitor.check_all()
    for alert in alerts:
        print(f"⚠️ {alert.lifecycle_id}: {alert.message}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .schema import (
    EvolutionConfig,
    LifecycleState,
    MonitoringConfig,
    StrategyLifecycle,
    TransitionRequest,
)

logger = logging.getLogger(__name__)


@dataclass
class MonitorAlert:
    """监控告警。"""
    lifecycle_id: str = ""
    strategy_name: str = ""
    current_state: str = ""
    severity: str = "info"  # info | warning | critical
    message: str = ""
    suggestion: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class TrialMonitor:
    """策略表现持续监控器。

    监控 TRIAL 和 ACTIVE 状态的策略，检测:
      - 最大回撤超标 → DEGRADED
      - Sharpe 持续低于阈值 → 建议优化
      - 连续 N 天表现不佳 → DEGRADED

    用法:
        monitor = TrialMonitor(manager, runner, config)
        alerts = monitor.check_all()
    """

    def __init__(
        self,
        lifecycle_manager: Any = None,  # LifecycleManager
        trial_runner: Any = None,       # TrialRunner
        config: Optional[EvolutionConfig] = None,
    ):
        self._manager = lifecycle_manager
        self._runner = trial_runner
        self._config = config or EvolutionConfig()
        self._degradation_counters: dict[str, int] = {}  # lifecycle_id → 连续低表现天数

    @property
    def monitoring_config(self) -> MonitoringConfig:
        return self._config.monitoring

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self) -> list[MonitorAlert]:
        """检查所有活跃策略，返回告警列表。"""
        alerts: list[MonitorAlert] = []

        if self._manager is None:
            return alerts

        monitored = self._manager.list_active_or_trial()
        for lc in monitored:
            lc_alerts = self._check_one(lc)
            alerts.extend(lc_alerts)

        return alerts

    def check_one(self, lifecycle_id: str) -> list[MonitorAlert]:
        """检查单个策略。"""
        if self._manager is None:
            return []
        lc = self._manager.get(lifecycle_id)
        if lc is None:
            return []
        return self._check_one(lc)

    def get_degradation_count(self, lifecycle_id: str) -> int:
        """获取连续表现不佳天数。"""
        return self._degradation_counters.get(lifecycle_id, 0)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_one(self, lc: StrategyLifecycle) -> list[MonitorAlert]:
        """检查单个策略的监控指标。"""
        alerts: list[MonitorAlert] = []
        cfg = self.monitoring_config

        # 获取当前指标
        if lc.state == LifecycleState.TRIAL:
            sharpe = lc.trial_sharpe or 0
            ret = lc.trial_return or 0
            max_dd = lc.trial_max_dd or 0
        elif lc.state == LifecycleState.ACTIVE:
            sharpe = lc.live_sharpe or 0
            ret = lc.live_return or 0
            max_dd = lc.live_max_dd or 0
        else:
            return alerts

        trial_cfg = self._config.trial

        # 最大回撤检查
        if max_dd > trial_cfg.max_drawdown_limit:
            alerts.append(MonitorAlert(
                lifecycle_id=lc.id,
                strategy_name=lc.strategy_name,
                current_state=lc.state.value,
                severity="critical",
                message=f"最大回撤 {max_dd:.1%} 超标 (>{trial_cfg.max_drawdown_limit:.0%})",
                suggestion="建议降级或撤退",
                metrics={"max_drawdown": max_dd},
            ))

        # Sharpe 检查
        if sharpe < trial_cfg.sharpe_superiority and lc.state == LifecycleState.ACTIVE:
            alerts.append(MonitorAlert(
                lifecycle_id=lc.id,
                strategy_name=lc.strategy_name,
                current_state=lc.state.value,
                severity="warning",
                message=f"Sharpe {sharpe:.2f} 低于阈值 {trial_cfg.sharpe_superiority:.2f}",
                suggestion="关注策略表现，考虑优化",
                metrics={"sharpe_ratio": sharpe},
            ))

        # 连续表现不佳检测
        is_underperforming = (
            (lc.state == LifecycleState.TRIAL and sharpe < trial_cfg.sharpe_superiority / 2)
            or (lc.state == LifecycleState.ACTIVE and sharpe < 0)
            or max_dd > trial_cfg.max_drawdown_limit * 0.8
        )

        if is_underperforming:
            self._degradation_counters[lc.id] = (
                self._degradation_counters.get(lc.id, 0) + 1
            )
            days = self._degradation_counters[lc.id]

            if days >= cfg.degradation_window_days:
                alerts.append(MonitorAlert(
                    lifecycle_id=lc.id,
                    strategy_name=lc.strategy_name,
                    current_state=lc.state.value,
                    severity="critical",
                    message=f"连续 {days} 天表现不佳，触发降级",
                    suggestion=(
                        "自动优化" if cfg.auto_optimize_on_degrade
                        else "建议手动打回或退役"
                    ),
                    metrics={"degradation_days": days},
                ))

                # 自动降级
                if cfg.auto_optimize_on_degrade and self._manager:
                    self._auto_degrade(lc)
        else:
            # 重置计数器
            if lc.id in self._degradation_counters:
                self._degradation_counters[lc.id] = 0

        return alerts

    def _auto_degrade(self, lc: StrategyLifecycle):
        """自动触发 DEGRADED → OPTIMIZING 流程。"""
        # 先转为 DEGRADED
        resp = self._manager.transition(TransitionRequest(
            lifecycle_id=lc.id,
            target_state=LifecycleState.DEGRADED,
            reason=f"监控自动降级: 连续 {self._degradation_counters.get(lc.id, 0)} 天表现不佳",
            triggered_by="monitor",
        ))

        if resp.result.value != "ok":
            logger.warning("自动降级失败 (%s): %s", lc.id, resp.message)
            return

        # 转为 OPTIMIZING
        if self.monitoring_config.auto_optimize_on_degrade:
            self._manager.transition(TransitionRequest(
                lifecycle_id=lc.id,
                target_state=LifecycleState.OPTIMIZING,
                reason="监控自动触发优化",
                triggered_by="monitor",
            ))
            logger.info("策略 %s (%s) 自动进入优化", lc.strategy_name, lc.id)

    def summary(self) -> str:
        """生成监控摘要。"""
        alerts = self.check_all()
        if not alerts:
            return "✅ 所有策略正常"

        critical = [a for a in alerts if a.severity == "critical"]
        warnings = [a for a in alerts if a.severity == "warning"]

        lines = ["📡 策略监控报告"]
        if critical:
            lines.append(f"\n🚨 严重告警 ({len(critical)} 条):")
            for a in critical:
                lines.append(f"  • [{a.strategy_name}] {a.message}")
                lines.append(f"    → {a.suggestion}")
        if warnings:
            lines.append(f"\n⚠️ 警告 ({len(warnings)} 条):")
            for a in warnings:
                lines.append(f"  • [{a.strategy_name}] {a.message}")
        return "\n".join(lines)
