# -*- coding: utf-8 -*-
"""管道对比器 — A/B对比验证架构论文的影响。

用途: 架构论文实施后，对比旧管道 vs 新管道的策略表现差异。

用法:
    comparator = PipelineComparator()
    result = comparator.compare(
        old_pipeline_result=old_result,
        new_pipeline_result=new_result,
    )
    print(result.report)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PipelineComparisonResult:
    """管道A/B对比结果。"""
    # 旧管道指标
    old_sharpe: float = 0.0
    old_return: float = 0.0
    old_max_dd: float = 0.0
    old_win_rate: float = 0.0
    old_trades: int = 0

    # 新管道指标
    new_sharpe: float = 0.0
    new_return: float = 0.0
    new_max_dd: float = 0.0
    new_win_rate: float = 0.0
    new_trades: int = 0

    # 对比
    sharpe_improvement_pct: float = 0.0
    return_improvement_pct: float = 0.0
    max_dd_improvement_pct: float = 0.0
    win_rate_change_pct: float = 0.0

    # 结论
    improved: bool = False
    recommendation: str = ""
    report: str = ""
    compared_at: str = field(default_factory=lambda: datetime.now().isoformat())


class PipelineComparator:
    """管道A/B对比器。

    对比架构改进前后的策略表现，判断是否有显著改善。

    用法:
        comparator = PipelineComparator()
        result = comparator.compare_metrics(
            old_sharpe=0.8, old_return=0.25, old_max_dd=0.20, old_win_rate=0.55,
            new_sharpe=1.1, new_return=0.35, new_max_dd=0.15, new_win_rate=0.60,
        )
        if result.improved:
            print("合入主管道")
    """

    # 改善阈值
    MIN_SHARPE_IMPROVEMENT = 0.05
    MIN_RETURN_IMPROVEMENT = 0.02
    MAX_DD_WORSENING_ALLOWED = 0.03

    def compare_metrics(
        self,
        old_sharpe: float,
        old_return: float,
        old_max_dd: float,
        old_win_rate: float = 0.0,
        old_trades: int = 0,
        new_sharpe: float = 0.0,
        new_return: float = 0.0,
        new_max_dd: float = 0.0,
        new_win_rate: float = 0.0,
        new_trades: int = 0,
    ) -> PipelineComparisonResult:
        """对比两组管道指标。

        Args:
            old_*: 旧管道指标
            new_*: 新管道指标

        Returns:
            PipelineComparisonResult
        """
        result = PipelineComparisonResult(
            old_sharpe=old_sharpe,
            old_return=old_return,
            old_max_dd=old_max_dd,
            old_win_rate=old_win_rate,
            old_trades=old_trades,
            new_sharpe=new_sharpe,
            new_return=new_return,
            new_max_dd=new_max_dd,
            new_win_rate=new_win_rate,
            new_trades=new_trades,
        )

        # 计算改善百分比
        if old_sharpe != 0:
            result.sharpe_improvement_pct = ((new_sharpe / old_sharpe) - 1) * 100
        result.return_improvement_pct = (new_return - old_return) * 100
        result.max_dd_improvement_pct = (old_max_dd - new_max_dd) * 100  # 正值=改善
        if old_win_rate > 0:
            result.win_rate_change_pct = (new_win_rate - old_win_rate) * 100

        # 判断是否改善
        sharpe_ok = new_sharpe >= old_sharpe + self.MIN_SHARPE_IMPROVEMENT
        return_ok = new_return >= old_return + self.MIN_RETURN_IMPROVEMENT
        dd_ok = new_max_dd <= old_max_dd + self.MAX_DD_WORSENING_ALLOWED

        result.improved = sharpe_ok and dd_ok  # 核心条件

        if result.improved and return_ok:
            result.recommendation = "✅ 建议合入 — 新管道在Sharpe和回撤上均有改善"
        elif result.improved:
            result.recommendation = "⚠️ 谨慎合入 — Sharpe改善但收益率提升不明显"
        elif sharpe_ok and not dd_ok:
            result.recommendation = "⚠️ 需要调整 — Sharpe改善但回撤加大"
        else:
            result.recommendation = "❌ 不建议合入 — 改善不显著"

        result.report = self._generate_report(result)
        return result

    def compare_from_results(
        self,
        old_result: Any,
        new_result: Any,
    ) -> PipelineComparisonResult:
        """从回测结果对象直接对比。"""
        return self.compare_metrics(
            old_sharpe=getattr(old_result, "sharpe_ratio", 0.0),
            old_return=getattr(old_result, "total_return", 0.0),
            old_max_dd=getattr(old_result, "max_drawdown", 0.0),
            old_win_rate=getattr(old_result, "win_rate", 0.0),
            old_trades=getattr(old_result, "total_trades", 0),
            new_sharpe=getattr(new_result, "sharpe_ratio", 0.0),
            new_return=getattr(new_result, "total_return", 0.0),
            new_max_dd=getattr(new_result, "max_drawdown", 0.0),
            new_win_rate=getattr(new_result, "win_rate", 0.0),
            new_trades=getattr(new_result, "total_trades", 0),
        )

    @staticmethod
    def _generate_report(result: PipelineComparisonResult) -> str:
        """生成对比报告。"""
        lines = [
            "📊 管道A/B对比报告",
            f"\n指标对比:",
            f"  {'指标':<20s} {'旧管道':>10s} {'新管道':>10s} {'变化':>10s}",
            f"  {'─' * 50}",
            f"  {'Sharpe Ratio':<20s} {result.old_sharpe:>10.2f} {result.new_sharpe:>10.2f} {result.sharpe_improvement_pct:>+9.1f}%",
            f"  {'Total Return':<20s} {result.old_return:>9.1%} {result.new_return:>9.1%} {result.return_improvement_pct:>+9.1f}%",
            f"  {'Max Drawdown':<20s} {result.old_max_dd:>9.1%} {result.new_max_dd:>9.1%} {result.max_dd_improvement_pct:>+9.1f}%",
            f"  {'Win Rate':<20s} {result.old_win_rate:>9.1%} {result.new_win_rate:>9.1%} {result.win_rate_change_pct:>+9.1f}%",
            f"\n结论: {result.recommendation}",
        ]
        return "\n".join(lines)
