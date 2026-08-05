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

    # P2-5: 样本外（OOS）验证 — 未提供 OOS 数据时恒为 True（向后兼容）
    oos_passed: bool = True
    oos_checks: dict[str, bool] = field(default_factory=dict)
    oos_metrics: dict[str, float] = field(default_factory=dict)
    oos_note: str = ""


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

    def __init__(
        self,
        thresholds: Optional[BacktestThresholds] = None,
        oos_min_sharpe: float = 0.0,
        oos_min_win_rate: float = 0.5,
        oos_max_overfit_return_gap: float = 15.0,
        oos_max_overfit_sharpe_drop: float = 0.5,
    ):
        self._thresholds = thresholds or BacktestThresholds()
        # P2-5: 样本外（OOS）门禁阈值（可选，默认不改变既有行为）
        self._oos_min_sharpe = oos_min_sharpe
        self._oos_min_win_rate = oos_min_win_rate
        self._oos_max_overfit_return_gap = oos_max_overfit_return_gap
        self._oos_max_overfit_sharpe_drop = oos_max_overfit_sharpe_drop

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
        oos_result: Any = None,
    ) -> BacktestValidationResult:
        """验证回测结果是否通过门禁。

        P2-5: 可选传入样本外（OOS）验证结果（如
        ``src.backtest.walkforward.WalkForwardResult``）。OOS 不达标 →
        ``oos_passed=False`` 且整体 ``passed=False``（不直接合入/部署）。
        未传 OOS 数据时 ``oos_passed`` 恒为 True（向后兼容）。

        Args:
            sharpe: 年化 Sharpe 比率
            total_return: 总收益率
            max_dd: 最大回撤 (绝对值, 如 0.15 = 15%)
            trades: 交易次数
            benchmark_return: 基准收益
            oos_result: 可选样本外验证结果对象（duck-typed，读取
                        avg_oos_sharpe / win_rate / is_overfit / 等属性）

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

        # P2-5: 样本外验证参与部署门禁
        oos_passed, oos_checks, oos_metrics, oos_note = self._check_oos(oos_result)
        if oos_result is not None and not oos_passed:
            failures.append(oos_note or "样本外（OOS）验证未通过")

        passed = all(checks.values()) and oos_passed

        report_lines = ["📊 回测验证报告", f"基准: {t.benchmark}"]
        for check, ok in checks.items():
            icon = "✅" if ok else "❌"
            report_lines.append(f"  {icon} {check}")
        if oos_metrics:
            report_lines.append(f"\n📈 样本外(OOS): {oos_note}")
            for check, ok in oos_checks.items():
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
            oos_passed=oos_passed,
            oos_checks=oos_checks,
            oos_metrics=oos_metrics,
            oos_note=oos_note,
        )

    def _check_oos(self, oos_result: Any) -> tuple[bool, dict[str, bool], dict[str, float], str]:
        """评估样本外（OOS）验证结果。

        Returns:
            (oos_passed, oos_checks, oos_metrics, oos_note)。
            oos_result 为 None 或缺少 OOS 指标 → (True, {}, {}, "")。
        """
        if oos_result is None:
            return True, {}, {}, ""

        oos_sharpe = getattr(oos_result, "avg_oos_sharpe", None)
        oos_win_rate = getattr(oos_result, "win_rate", None)
        is_overfit_fn = getattr(oos_result, "is_overfit", None)

        if oos_sharpe is None:
            return True, {}, {}, ""

        overfit = False
        if callable(is_overfit_fn):
            try:
                overfit = bool(is_overfit_fn())
            except Exception:
                overfit = False
        # 兜底: 直接用 IS→OOS gap 阈值判断过拟合
        if getattr(oos_result, "avg_is_oos_return_gap", 0.0) > self._oos_max_overfit_return_gap:
            overfit = True
        if getattr(oos_result, "avg_is_oos_sharpe_drop", 0.0) > self._oos_max_overfit_sharpe_drop:
            overfit = True

        oos_checks = {
            "oos_sharpe": oos_sharpe >= self._oos_min_sharpe,
            "oos_not_overfit": not overfit,
        }
        if oos_win_rate is not None:
            oos_checks["oos_win_rate"] = oos_win_rate >= self._oos_min_win_rate

        oos_passed = all(oos_checks.values())
        oos_metrics = {
            "avg_oos_sharpe": oos_sharpe,
            "win_rate": oos_win_rate if oos_win_rate is not None else -1.0,
            "avg_is_oos_return_gap": getattr(oos_result, "avg_is_oos_return_gap", 0.0),
            "avg_is_oos_sharpe_drop": getattr(oos_result, "avg_is_oos_sharpe_drop", 0.0),
        }

        note = (
            f"avg_oos_sharpe={oos_sharpe:.2f}"
            + (f", win_rate={oos_win_rate:.0%}" if oos_win_rate is not None else "")
            + (", ⚠️过拟合" if overfit else "")
        )
        if not oos_passed:
            note = "样本外(OOS)未达标 — " + note

        return oos_passed, oos_checks, oos_metrics, note

    def validate_from_engine_result(
        self,
        engine_result: Any,
        benchmark_return: float = 0.0,
        oos_result: Any = None,
    ) -> BacktestValidationResult:
        """从回测引擎结果直接验证。

        Args:
            engine_result: 回测引擎输出的结果对象（需有 sharpe_ratio,
                           total_return, max_drawdown, total_trades 属性）
            benchmark_return: 基准收益
            oos_result: 可选样本外验证结果对象（P2-5）
        """
        return self.validate(
            sharpe=getattr(engine_result, "sharpe_ratio", 0.0),
            total_return=getattr(engine_result, "total_return", 0.0),
            max_dd=getattr(engine_result, "max_drawdown", 0.0),
            trades=getattr(engine_result, "total_trades", 0),
            benchmark_return=benchmark_return,
            oos_result=oos_result,
        )
