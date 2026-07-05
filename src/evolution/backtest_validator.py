# -*- coding: utf-8 -*-
"""回测验证器 — 回测门禁，使用可配置阈值判断策略是否通过。

用法:
    validator = BacktestValidator(config.backtest)
    result = validator.validate(sharpe=1.2, total_return=0.35, max_dd=0.15, trades=50)
    print(result.passed, result.report)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .schema import BacktestThresholds

logger = logging.getLogger(__name__)


@dataclass
class BacktestValidationResult:
    """回测验证结果。"""
    passed: bool = False
    sharpe_ratio: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    total_trades: int = 0
    benchmark_return: float = 0.0
    excess_return: float = 0.0

    # 各指标是否达标
    checks: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    report: str = ""
    checked_at: str = field(default_factory=lambda: datetime.now().isoformat())


class BacktestValidator:
    """回测门禁验证器。

    按可配置阈值检查回测结果是否通过。
    所有阈值从 BacktestThresholds 读取。

    用法:
        validator = BacktestValidator(thresholds)
        result = validator.validate(
            sharpe=engine_result.sharpe_ratio,
            total_return=engine_result.total_return,
            max_dd=engine_result.max_drawdown,
            trades=engine_result.total_trades,
        )
        if result.passed:
            # 进入 CANDIDATE 状态
            ...
    """

    def __init__(self, thresholds: Optional[BacktestThresholds] = None):
        self._thresholds = thresholds or BacktestThresholds()

    @property
    def thresholds(self) -> BacktestThresholds:
        return self._thresholds

    def update_thresholds(self, new_thresholds: BacktestThresholds):
        """更新阈值配置。"""
        self._thresholds = new_thresholds

    def validate(
        self,
        sharpe: float,
        total_return: float,
        max_dd: float,
        trades: int,
        benchmark_return: float = 0.0,
    ) -> BacktestValidationResult:
        """验证回测结果是否通过门禁。

        Args:
            sharpe: 年化 Sharpe 比率
            total_return: 总收益率
            max_dd: 最大回撤 (绝对值, 如 0.15 = 15%)
            trades: 交易次数
            benchmark_return: 基准收益

        Returns:
            BacktestValidationResult
        """
        t = self._thresholds
        excess = total_return - benchmark_return

        checks = {
            "sharpe_ratio": sharpe >= t.min_sharpe_ratio,
            "total_return": total_return >= t.min_total_return,
            "max_drawdown": max_dd <= t.max_max_drawdown,
            "min_trades": trades >= t.min_trades,
        }

        failures = []
        if not checks["sharpe_ratio"]:
            failures.append(
                f"Sharpe {sharpe:.2f} < 阈值 {t.min_sharpe_ratio}"
            )
        if not checks["total_return"]:
            failures.append(
                f"收益率 {total_return:.1%} < 阈值 {t.min_total_return:.0%}"
            )
        if not checks["max_drawdown"]:
            failures.append(
                f"最大回撤 {max_dd:.1%} > 阈值 {t.max_max_drawdown:.0%}"
            )
        if not checks["min_trades"]:
            failures.append(
                f"交易次数 {trades} < 阈值 {t.min_trades}"
            )

        passed = all(checks.values())

        report_lines = ["📊 回测验证报告", f"基准: {t.benchmark}"]
        for check, ok in checks.items():
            icon = "✅" if ok else "❌"
            report_lines.append(f"  {icon} {check}")
        if failures:
            report_lines.append(f"\n⚠️ 未通过原因:")
            for f_msg in failures:
                report_lines.append(f"  • {f_msg}")
        if passed:
            report_lines.append("\n✅ 回测通过 — 可进入候选池")
        else:
            report_lines.append("\n❌ 回测未通过 — 不可进入候选池")

        return BacktestValidationResult(
            passed=passed,
            sharpe_ratio=sharpe,
            total_return=total_return,
            max_drawdown=max_dd,
            total_trades=trades,
            benchmark_return=benchmark_return,
            excess_return=excess,
            checks=checks,
            failures=failures,
            report="\n".join(report_lines),
        )

    def validate_from_engine_result(
        self,
        engine_result: Any,
        benchmark_return: float = 0.0,
    ) -> BacktestValidationResult:
        """从回测引擎结果直接验证。

        Args:
            engine_result: 回测引擎输出的结果对象（需有 sharpe_ratio,
                           total_return, max_drawdown, total_trades 属性）
            benchmark_return: 基准收益
        """
        return self.validate(
            sharpe=getattr(engine_result, "sharpe_ratio", 0.0),
            total_return=getattr(engine_result, "total_return", 0.0),
            max_dd=getattr(engine_result, "max_drawdown", 0.0),
            trades=getattr(engine_result, "total_trades", 0),
            benchmark_return=benchmark_return,
        )
