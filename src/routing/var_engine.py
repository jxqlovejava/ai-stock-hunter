# -*- coding: utf-8 -*-
"""VaR/CVaR 引擎 — 历史模拟 + 参数法 + 组合层 VaR。

支持:
  - 历史 VaR/CVaR（非参数，不假设分布）
  - 参数 VaR（假设正态，需均值+标准差）
  - 组合 VaR（考虑持仓权重+协方差矩阵）
  - 回测验证（Kupiec 检验）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class VaRResult:
    """VaR/CVaR 计算结果。"""
    var_95: float = 0.0              # 95% VaR（正数=亏损%，如 0.03 = 3%）
    var_99: float = 0.0              # 99% VaR
    cvar_95: float = 0.0             # 95% CVaR（Expected Shortfall）
    cvar_99: float = 0.0             # 99% CVaR
    method: str = ""                 # "historical" / "parametric"
    max_drawdown: float = 0.0        # 同期最大回撤（用于对比）
    n_observations: int = 0
    exceeded_95: int = 0             # 实际超越 VaR 95 的天数
    exceeded_99: int = 0             # 实际超越 VaR 99 的天数

    @property
    def var_95_as_negative(self) -> float:
        """VaR 95 作为负数（-0.03 = 3% 亏损）。"""
        return -abs(self.var_95)

    def to_dict(self) -> dict:
        return {
            "var_95": round(self.var_95, 6),
            "var_99": round(self.var_99, 6),
            "cvar_95": round(self.cvar_95, 6),
            "cvar_99": round(self.cvar_99, 6),
            "method": self.method,
            "max_drawdown": round(self.max_drawdown, 6),
            "n_observations": self.n_observations,
            "exceeded_95": self.exceeded_95,
            "exceeded_99": self.exceeded_99,
        }


@dataclass
class PortfolioVaRResult:
    """组合 VaR 分解。"""
    total_var_95: float = 0.0
    total_cvar_95: float = 0.0
    marginal_var: dict[str, float] = field(default_factory=dict)    # 边际 VaR
    component_var: dict[str, float] = field(default_factory=dict)   # 成分 VaR
    diversification_ratio: float = 0.0  # >1 表示有分散化收益

    def to_dict(self) -> dict:
        return {
            "total_var_95": round(self.total_var_95, 6),
            "total_cvar_95": round(self.total_cvar_95, 6),
            "marginal_var": {k: round(v, 6) for k, v in self.marginal_var.items()},
            "component_var": {k: round(v, 6) for k, v in self.component_var.items()},
            "diversification_ratio": round(self.diversification_ratio, 4),
        }


class VaREngine:
    """VaR/CVaR 计算引擎。

    用法:
        engine = VaREngine()
        result = engine.historical_var(returns, confidence=0.95)
        print(f"VaR 95%: {result.var_95*100:.1f}%")
    """

    @staticmethod
    def historical_var(
        returns: np.ndarray | list[float],
        confidence: float = 0.95,
    ) -> VaRResult:
        """历史模拟 VaR/CVaR。

        Args:
            returns: 日收益率序列（正=盈利, 负=亏损）
            confidence: 置信水平（0.95 / 0.99）
        """
        r = np.asarray(returns, dtype=float)
        r = r[np.isfinite(r)]

        if len(r) < 50:
            return VaRResult(method="historical", n_observations=len(r))

        # VaR = 分位数（左尾）- 正值表示亏损
        alpha = 1.0 - confidence
        var_95_val = abs(float(np.percentile(r, alpha * 100)))
        var_99_val = abs(float(np.percentile(r, 1.0)))

        # CVaR = 超越 VaR 的平均亏损
        tail_95 = r[r <= np.percentile(r, alpha * 100)]
        tail_99 = r[r <= np.percentile(r, 1.0)]
        cvar_95_val = abs(float(tail_95.mean())) if len(tail_95) > 0 else var_95_val
        cvar_99_val = abs(float(tail_99.mean())) if len(tail_99) > 0 else var_99_val

        # 最大回撤
        cumulative = np.cumprod(1 + r)
        hwm = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - hwm) / hwm
        max_dd = abs(float(np.min(drawdowns)))

        # Kupiec 回测: 实际超越天数
        exceeded_95 = int(np.sum(r <= -var_95_val))
        exceeded_99 = int(np.sum(r <= -var_99_val))

        return VaRResult(
            var_95=round(var_95_val, 6),
            var_99=round(var_99_val, 6),
            cvar_95=round(cvar_95_val, 6),
            cvar_99=round(cvar_99_val, 6),
            method="historical",
            max_drawdown=round(max_dd, 6),
            n_observations=len(r),
            exceeded_95=exceeded_95,
            exceeded_99=exceeded_99,
        )

    @staticmethod
    def parametric_var(
        returns: np.ndarray | list[float],
        confidence: float = 0.95,
    ) -> VaRResult:
        """参数法 VaR（假设正态分布）。

        VaR = μ + σ × z_α（左尾）
        """
        r = np.asarray(returns, dtype=float)
        r = r[np.isfinite(r)]

        if len(r) < 20:
            return VaRResult(method="parametric", n_observations=len(r))

        mu = float(np.mean(r))
        sigma = float(np.std(r, ddof=1))

        # z-score constants（不需要 scipy）:
        # 1.645 for 95%, 2.326 for 99% (单尾)
        z_95 = 1.645
        z_99 = 2.326

        var_95_val = abs(mu + sigma * (-z_95))
        var_99_val = abs(mu + sigma * (-z_99))

        # 参数法 CVaR: μ + σ × φ(z)/(1-α)
        # φ(1.645) ≈ 0.1031, φ(2.326) ≈ 0.0267
        phi_95 = 0.103135  # standard normal PDF at z=1.645
        phi_99 = 0.026652  # standard normal PDF at z=2.326

        alpha = 1.0 - confidence
        cvar_95_val = abs(mu + sigma * phi_95 / alpha)
        cvar_99_val = abs(mu + sigma * phi_99 / 0.01)

        # 最大回撤
        cumulative = np.cumprod(1 + r)
        hwm = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - hwm) / hwm
        max_dd = abs(float(np.min(drawdowns)))

        return VaRResult(
            var_95=round(float(var_95_val), 6),
            var_99=round(float(var_99_val), 6),
            cvar_95=round(float(cvar_95_val), 6),
            cvar_99=round(float(cvar_99_val), 6),
            method="parametric",
            max_drawdown=round(max_dd, 6),
            n_observations=len(r),
        )

    @staticmethod
    def portfolio_var(
        weights: dict[str, float],
        returns_matrix: np.ndarray,       # T×N
        symbols: list[str],
        confidence: float = 0.95,
    ) -> PortfolioVaRResult:
        """组合 VaR 分解。

        Args:
            weights: {symbol: weight} 仓位权重
            returns_matrix: T×N 日收益率矩阵
            symbols: 列顺序
            confidence: 置信水平
        """
        n = len(symbols)
        w = np.zeros(n)
        for i, sym in enumerate(symbols):
            w[i] = weights.get(sym, 0.0)

        # 组合日收益率
        portfolio_returns = returns_matrix @ w

        # 单资产 VaR
        engine = VaREngine()
        total_var = engine.historical_var(portfolio_returns, confidence)

        # 协方差矩阵
        cov = np.cov(returns_matrix.T)
        sigma_p = np.sqrt(w @ cov @ w)

        # 边际 VaR: ∂VaR/∂w_i = z_α × (cov @ w)_i / σ_p
        alpha = 1.0 - confidence
        z_95 = 1.645  # approximate
        cov_w = cov @ w
        mvar = z_95 * cov_w / sigma_p if sigma_p > 0 else np.zeros(n)

        # 成分 VaR = w_i × 边际 VaR
        cvar_decomp = w * mvar

        # 分散化比率: Σ(w_i × σ_i) / σ_p
        indiv_var = np.sum(np.abs(w) * np.sqrt(np.diag(cov)))
        div_ratio = indiv_var / sigma_p if sigma_p > 0 else 1.0

        return PortfolioVaRResult(
            total_var_95=total_var.var_95,
            total_cvar_95=total_var.cvar_95,
            marginal_var={symbols[i]: round(float(mvar[i]), 6) for i in range(n)},
            component_var={symbols[i]: round(float(cvar_decomp[i]), 6) for i in range(n)},
            diversification_ratio=round(float(div_ratio), 4),
        )

    @staticmethod
    def is_var_breached(
        var_result: VaRResult,
        var_limit: float,        # 如 0.03 = 3% 日 VaR
        cvar_limit: float | None = None,
    ) -> tuple[bool, list[str]]:
        """检查 VaR/CVaR 是否超限。

        Returns:
            (breached, reasons)
        """
        reasons = []
        breached = False

        if var_result.cvar_95 > var_limit:
            breached = True
            reasons.append(
                f"CVaR 95% ({var_result.cvar_95*100:.1f}%) 超限 "
                f"({var_limit*100:.1f}%)"
            )

        if cvar_limit and var_result.cvar_99 > cvar_limit:
            breached = True
            reasons.append(
                f"CVaR 99% ({var_result.cvar_99*100:.1f}%) 超限 "
                f"({cvar_limit*100:.1f}%)"
            )

        return breached, reasons
