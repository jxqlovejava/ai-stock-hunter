# -*- coding: utf-8 -*-
"""策略横向对比器。

支持多策略在同一时间段的多维度对比，输出排名和综合评分。

用法:
    comparator = StrategyComparator()
    results = {
        "MVP1_v1.0": result1,
        "MVP1_v1.1": result2,
        "MVP2_v1.0": result3,
    }
    report = comparator.compare(results)
    print(report)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .engine import BacktestResult


@dataclass
class StrategyRanking:
    """策略排名项。"""

    name: str
    rank: int
    composite_score: float  # 0-100 综合评分
    sharpe_ratio: float
    total_return: float
    max_drawdown: float
    win_rate: float
    annual_return: float
    total_trades: int
    details: dict[str, float] = field(default_factory=dict)


class StrategyComparator:
    """多策略横向对比器。

    综合评分权重:
      - Sharpe 比率: 40%
      - 最大回撤（取绝对值后的倒数归一化）: 25%
      - 胜率: 20%
      - 年化收益: 15%
    """

    # 综合评分权重
    WEIGHTS = {
        "sharpe_ratio": 0.40,
        "max_drawdown": 0.25,
        "win_rate": 0.20,
        "annual_return": 0.15,
    }

    def compare(self, results: dict[str, BacktestResult]) -> list[StrategyRanking]:
        """对比多个策略的回测结果。

        Args:
            results: {策略名: BacktestResult} 字典

        Returns:
            按综合评分降序排列的排名列表
        """
        if not results:
            return []

        rankings = []
        for name, result in results.items():
            rankings.append(StrategyRanking(
                name=name,
                rank=0,
                composite_score=0.0,
                sharpe_ratio=result.sharpe_ratio,
                total_return=result.total_return,
                max_drawdown=result.max_drawdown,
                win_rate=result.win_rate,
                annual_return=result.annual_return,
                total_trades=result.total_trades,
            ))

        # 归一化各指标
        sharpe_vals = [r.sharpe_ratio for r in rankings]
        dd_vals = [abs(r.max_drawdown) if r.max_drawdown != 0 else 0.01 for r in rankings]
        win_vals = [r.win_rate for r in rankings]
        ret_vals = [r.annual_return for r in rankings]

        for i, r in enumerate(rankings):
            s_norm = self._normalize(r.sharpe_ratio, sharpe_vals, higher_better=True)
            d_norm = self._normalize(1.0 / dd_vals[i], [1.0 / d for d in dd_vals], higher_better=True)
            w_norm = self._normalize(r.win_rate, win_vals, higher_better=True)
            a_norm = self._normalize(r.annual_return, ret_vals, higher_better=True)

            r.composite_score = (
                s_norm * self.WEIGHTS["sharpe_ratio"]
                + d_norm * self.WEIGHTS["max_drawdown"]
                + w_norm * self.WEIGHTS["win_rate"]
                + a_norm * self.WEIGHTS["annual_return"]
            ) * 100

        # 排序
        rankings.sort(key=lambda x: x.composite_score, reverse=True)
        for i, r in enumerate(rankings):
            r.rank = i + 1

        return rankings

    def report(self, rankings: list[StrategyRanking]) -> str:
        """生成对比报告。"""
        if not rankings:
            return "无策略数据可供对比。"

        lines = [
            "# 策略横向对比报告",
            "",
            "| 排名 | 策略 | 综合评分 | Sharpe | 年化收益 | 最大回撤 | 胜率 | 交易数 |",
            "|------|------|---------|--------|---------|---------|------|--------|",
        ]

        for r in rankings:
            lines.append(
                f"| {r.rank} | {r.name} | {r.composite_score:.1f} | "
                f"{r.sharpe_ratio:.2f} | {r.annual_return:.2%} | "
                f"{r.max_drawdown:.2%} | {r.win_rate:.2%} | {r.total_trades} |"
            )

        lines.append("")
        best = rankings[0]
        lines.append(f"🏆 最优策略: **{best.name}** (综合评分: {best.composite_score:.1f})")

        return "\n".join(lines)

    def find_best(self, results: dict[str, BacktestResult]) -> Optional[StrategyRanking]:
        """快速找到最优策略。"""
        rankings = self.compare(results)
        return rankings[0] if rankings else None

    def compare_metric(
        self,
        results: dict[str, BacktestResult],
        metric: str,
    ) -> list[tuple[str, float]]:
        """按单一指标排序。

        Args:
            results: {策略名: BacktestResult}
            metric: 指标名 (sharpe_ratio, total_return, max_drawdown, win_rate, annual_return)

        Returns:
            [(策略名, 指标值), ...] 按优排序
        """
        higher_better = {
            "sharpe_ratio": True,
            "total_return": True,
            "annual_return": True,
            "win_rate": True,
            "max_drawdown": False,
        }

        items = [(name, getattr(r, metric, 0) or 0) for name, r in results.items()]
        # 所有指标均按"最优在前"排序：值越大越好（包括 max_drawdown 因它是负数，
        # -0.10 > -0.40，所以降序即可把最优排在前面）
        items.sort(key=lambda x: x[1], reverse=True)
        return items

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(
        value: float,
        all_values: list[float],
        higher_better: bool = True,
    ) -> float:
        """Min-max 归一化到 [0, 1]。"""
        if not all_values:
            return 0.0
        mn = min(all_values)
        mx = max(all_values)
        if mx == mn:
            return 0.5
        norm = (value - mn) / (mx - mn)
        if not higher_better:
            norm = 1.0 - norm
        return max(0.0, min(1.0, norm))
