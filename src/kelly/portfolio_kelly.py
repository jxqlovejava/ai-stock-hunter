# -*- coding: utf-8 -*-
"""组合层凯利仓位管理 — 协方差调整的凯利公式。

单标的凯利: f* = (b×p - q) / b（逐票独立）
组合凯利:   F* = Σ⁻¹ × μ（协方差矩阵逆 × 预期收益向量）

问题：买 5 只高度相关的票，每只单标的凯利说"10%"，组合实际暴露 50% 同向。
组合凯利通过协方差矩阵惩罚相关性，自动降低高相关标的的仓位。

用法:
    sizer = PortfolioKellySizer(trade_tracker, optimizer)
    targets = sizer.allocate(symbols, portfolio_value, prices)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from src.kelly.tracker import TradeTracker, KellyParams
from src.utils.decimal_utils import D

logger = logging.getLogger(__name__)


@dataclass
class PortfolioTarget:
    """组合层仓位目标。"""
    symbol: str
    target_weight: float          # 0.0-1.0
    kelly_f_stock: float = 0.0    # 单标的凯利 f*
    kelly_f_portfolio: float = 0.0  # 组合调整后凯利
    diversification_penalty: float = 0.0  # 相关性惩罚比例
    method: str = ""              # "portfolio_kelly" / "stock_only" / "fallback_equal"
    win_rate: float = 0.0
    payoff_ratio: float = 0.0
    n_trades: int = 0


@dataclass
class PortfolioAllocation:
    """组合分配结果。"""
    targets: list[PortfolioTarget] = field(default_factory=list)
    total_weight: float = 0.0     # 总仓位
    avg_diversification_penalty: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_summary(self) -> str:
        lines = [f"组合分配: {len(self.targets)} 标的, 总仓位 {self.total_weight:.1%}"]
        for t in self.targets:
            lines.append(
                f"  {t.symbol}: 单票凯利 {t.kelly_f_stock:.1%} → "
                f"组合凯利 {t.kelly_f_portfolio:.1%} "
                f"(分散惩罚 {t.diversification_penalty:.1%}) [{t.method}]"
            )
        if self.notes:
            lines.append(f"  ⚠️ {'; '.join(self.notes)}")
        return "\n".join(lines)


class PortfolioKellySizer:
    """组合层凯利仓位分配器。

    算法:
      1. 对每标的计算单票凯利 f*_i（通过 TradeTracker）
      2. 构造预期收益向量 μ_i = f*_i（凯利 f* 等价于最优仓位=预期超额收益/方差）
      3. 从历史收益率计算协方差矩阵 Σ
      4. F* = Σ⁻¹ × μ（无约束）/ 带权重上限约束

    冷启动回退（n<20）:
      单票凯利 × (1/√N) 分散化折扣
    """

    MIN_SAMPLES = 20  # 组合凯利最小样本数

    def __init__(
        self,
        trade_tracker: TradeTracker,
        kelly_fraction: float = 0.5,
        max_single_weight: float = 0.20,
        max_total_weight: float = 0.80,
    ):
        self._tracker = trade_tracker
        self._kelly_fraction = kelly_fraction
        self._max_single = max_single_weight
        self._max_total = max_total_weight

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def allocate(
        self,
        symbols: list[str],
        prices: dict[str, float],
        portfolio_value: float,
        returns_matrix: Optional[np.ndarray] = None,  # T×N 日收益率矩阵
    ) -> PortfolioAllocation:
        """计算组合层仓位分配。

        Args:
            symbols: 候选标的列表
            prices: {symbol: current_price}
            portfolio_value: 组合总价值
            returns_matrix: T×N 历史日收益率矩阵（列顺序对应 symbols）

        Returns:
            组合分配结果
        """
        targets: list[PortfolioTarget] = []
        notes: list[str] = []

        # 1. 计算每标的单票凯利
        stock_kellys: dict[str, float] = {}
        for sym in symbols:
            kp = self._tracker.get_kelly_params(sym)
            if kp.is_hot:
                f_star = float(D(kp.kelly_f))
            else:
                f_star = 0.0  # 冷启动 → 0（依赖回退逻辑）
            stock_kellys[sym] = f_star

        # 2. 检查是否有足够多热启动标的
        hot_symbols = [s for s in symbols if stock_kellys.get(s, 0) > 0]
        n_hot = len(hot_symbols)

        if n_hot < 2 or returns_matrix is None:
            # 回退: 单票凯利 × 分散化折扣
            return self._fallback_diversified(symbols, stock_kellys, notes)

        # 3. 构造预期收益向量和协方差矩阵
        n = len(symbols)
        mu = np.zeros(n)
        for i, sym in enumerate(symbols):
            mu[i] = stock_kellys.get(sym, 0.0)

        if returns_matrix.shape[1] != n:
            notes.append(f"收益率矩阵列数({returns_matrix.shape[1]}) ≠ 标的数({n})，回退")
            return self._fallback_diversified(symbols, stock_kellys, notes)

        # 只对热启动标的做组合优化
        hot_idx = [i for i, s in enumerate(symbols) if stock_kellys.get(s, 0) > 0]
        if len(hot_idx) < 2:
            return self._fallback_diversified(symbols, stock_kellys, notes)

        cov = np.cov(returns_matrix[:, hot_idx].T)
        mu_hot = mu[hot_idx]

        # 凯利组合: F* = (1/γ) × Σ⁻¹ × μ，γ=1 for log-optimal
        try:
            cov_inv = np.linalg.inv(cov)
            raw_weights = cov_inv @ mu_hot
        except np.linalg.LinAlgError:
            # 伪逆回退
            notes.append("协方差矩阵不可逆，使用伪逆")
            cov_inv = np.linalg.pinv(cov)
            raw_weights = cov_inv @ mu_hot

        # 归一化 + 缩放到总上限
        abs_sum = np.sum(np.abs(raw_weights))
        if abs_sum > 1e-8:
            scaled = raw_weights / abs_sum * self._max_total
        else:
            notes.append("所有凯利 f* ≤ 0，不建仓")
            return PortfolioAllocation(targets=[], total_weight=0.0, notes=notes)

        # 4. 应用分数凯利 + 上限约束
        portfolio_weights = np.zeros(n)
        total_w = 0.0
        for j, i in enumerate(hot_idx):
            pw = float(scaled[j]) * self._kelly_fraction
            pw = min(pw, self._max_single)
            pw = max(pw, 0.0)
            portfolio_weights[i] = pw
            total_w += pw

        # 5. 计算分散化惩罚
        for i, sym in enumerate(symbols):
            f_stock = stock_kellys.get(sym, 0.0) * self._kelly_fraction
            f_port = portfolio_weights[i]
            penalty = max(0.0, f_stock - f_port)

            targets.append(PortfolioTarget(
                symbol=sym,
                target_weight=round(float(f_port), 4),
                kelly_f_stock=round(float(stock_kellys.get(sym, 0.0)), 4),
                kelly_f_portfolio=round(float(f_port), 4),
                diversification_penalty=round(float(penalty), 4),
                method="portfolio_kelly" if i in hot_idx else "fallback_equal",
                win_rate=0.0,
                payoff_ratio=0.0,
                n_trades=0,
            ))

        return PortfolioAllocation(
            targets=targets,
            total_weight=round(float(total_w), 4),
            avg_diversification_penalty=round(
                float(np.mean([t.diversification_penalty for t in targets])), 4,
            ),
            notes=notes,
        )

    # ------------------------------------------------------------------
    # 回退
    # ------------------------------------------------------------------

    def _fallback_diversified(
        self,
        symbols: list[str],
        stock_kellys: dict[str, float],
        notes: list[str],
    ) -> PortfolioAllocation:
        """冷启动/数据不足时的回退: 单票凯利 × 1/√N。"""
        n = len(symbols)
        if n == 0:
            return PortfolioAllocation(targets=[], total_weight=0.0, notes=notes)

        discount = 1.0 / np.sqrt(max(n, 1)) if n > 1 else 1.0
        notes.append(f"回退模式: 单票凯利 × 1/√{n} = {discount:.2f} 分散化折扣")

        targets = []
        total_w = 0.0
        for sym in symbols:
            f_stock = stock_kellys.get(sym, 0.0)
            f_port = f_stock * self._kelly_fraction * discount
            f_port = min(f_port, self._max_single)
            penalty = max(0.0, f_stock * self._kelly_fraction - f_port)

            targets.append(PortfolioTarget(
                symbol=sym,
                target_weight=round(float(f_port), 4),
                kelly_f_stock=round(float(f_stock), 4),
                kelly_f_portfolio=round(float(f_port), 4),
                diversification_penalty=round(float(penalty), 4),
                method="fallback_diversified",
                win_rate=0.0, payoff_ratio=0.0, n_trades=0,
            ))
            total_w += f_port

        return PortfolioAllocation(
            targets=targets,
            total_weight=round(float(min(total_w, self._max_total)), 4),
            avg_diversification_penalty=round(
                float(np.mean([t.diversification_penalty for t in targets])), 4,
            ),
            notes=notes,
        )


# ------------------------------------------------------------------
# 便捷函数
# ------------------------------------------------------------------

def portfolio_kelly_allocate(
    trade_tracker: TradeTracker,
    symbols: list[str],
    prices: dict[str, float],
    portfolio_value: float,
    returns_matrix: Optional[np.ndarray] = None,
    kelly_fraction: float = 0.5,
) -> PortfolioAllocation:
    """便捷函数: 一键组合凯利分配。"""
    sizer = PortfolioKellySizer(trade_tracker, kelly_fraction=kelly_fraction)
    return sizer.allocate(symbols, prices, portfolio_value, returns_matrix)
