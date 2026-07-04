# -*- coding: utf-8 -*-
"""用户能力画像。

Phase 4: 月度能力雷达图（选股/择时/风控/情绪）。
每个维度有明确计算公式。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserProfile:
    """用户能力画像。"""
    stock_selection: float = 50.0      # 0-100: 选股能力
    timing: float = 50.0               # 0-100: 择时能力
    risk_discipline: float = 50.0      # 0-100: 风控纪律
    emotion_control: float = 50.0      # 0-100: 情绪控制
    strategy_contribution: float = 50.0  # 0-100: 策略贡献度（用户独立决策 vs 系统辅助）

    @property
    def summary(self) -> str:
        lines = [
            "# 用户能力画像",
            f"选股: {self.stock_selection:.0f}/100 — 独立选股 T+1M 收益排名分位数",
            f"择时: {self.timing:.0f}/100 — 买入后 N 日超额收益均值",
            f"风控: {self.risk_discipline:.0f}/100 — 止损执行率",
            f"情绪: {self.emotion_control:.0f}/100 — 系统建议遵从率",
            f"策略: {self.strategy_contribution:.0f}/100 — 系统辅助 vs 独立决策",
        ]
        return "\n".join(lines)


class ProfileTracker:
    """用户能力追踪器。

    计算公式:
      - 选股能力 = 用户独立选择的股票池 T+1 月收益在全市场排名分位数 × 100
      - 择时能力 = (1 - |买入后 20 日超额收益 - 市场均值| / 市场均值) × 100
      - 风控纪律 = 止损执行次数 / 应止损次数 × 100
      - 情绪控制 = 系统建议遵从率 × 100
    """

    def __init__(self):
        self._trades: list[dict] = []

    def record_trade(
        self,
        symbol: str,
        is_independent: bool,
        return_1m: float,
        benchmark_return_1m: float,
        stop_loss_executed: bool,
        stop_loss_needed: bool,
        followed_system: bool,
    ):
        """记录一笔交易用于画像计算。"""
        self._trades.append({
            "symbol": symbol,
            "is_independent": is_independent,
            "return_1m": return_1m,
            "benchmark_return_1m": benchmark_return_1m,
            "stop_loss_executed": stop_loss_executed,
            "stop_loss_needed": stop_loss_needed,
            "followed_system": followed_system,
        })

    def evaluate(self) -> UserProfile:
        """基于历史交易计算当前能力画像。"""
        if not self._trades:
            return UserProfile()

        # 选股: 独立选股的超额收益均值
        independent = [t for t in self._trades if t["is_independent"]]
        if independent:
            excess = [t["return_1m"] - t["benchmark_return_1m"] for t in independent]
            avg_excess = sum(excess) / len(excess)
            stock_score = max(0, min(100, 50 + avg_excess * 200))
        else:
            stock_score = 50.0

        # 择时: 超额收益均值取绝对值
        all_excess = [t["return_1m"] - t["benchmark_return_1m"] for t in self._trades]
        if all_excess:
            mean_excess = sum(all_excess) / len(all_excess)
            timing_score = max(0, min(100, 50 + mean_excess * 200))
        else:
            timing_score = 50.0

        # 风控: 止损执行率
        needed = sum(1 for t in self._trades if t["stop_loss_needed"])
        executed = sum(1 for t in self._trades if t["stop_loss_executed"])
        risk_score = (executed / needed * 100) if needed > 0 else 100.0

        # 情绪: 系统遵从率
        total = len(self._trades)
        followed = sum(1 for t in self._trades if t["followed_system"])
        emotion_score = (followed / total * 100) if total > 0 else 100.0

        return UserProfile(
            stock_selection=stock_score,
            timing=timing_score,
            risk_discipline=risk_score,
            emotion_control=emotion_score,
            strategy_contribution=50.0 + (emotion_score - 50.0) * 0.5,  # 遵从度高 → 策略贡献度上升
        )
