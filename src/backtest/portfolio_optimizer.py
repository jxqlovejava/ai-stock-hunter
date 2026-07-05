"""Portfolio optimization — risk parity, mean-variance, Black-Litterman.

Provides position sizing beyond simple equal-weight, using scipy.optimize
for convex optimization. Falls back to equal-weight if scipy unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PortfolioWeights:
    """Optimized portfolio weight allocation."""

    symbols: list[str] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    method: str = "equal"  # "equal" / "risk_parity" / "mean_variance" / "black_litterman"
    expected_return: Optional[float] = None  # Annualized expected return
    expected_risk: Optional[float] = None  # Annualized volatility
    sharpe_ratio: Optional[float] = None


class PortfolioOptimizer:
    """Portfolio weight optimizer with multiple methods."""

    def __init__(self):
        self._has_scipy = False
        try:
            import scipy.optimize  # noqa: F401
            self._has_scipy = True
        except ImportError:
            logger.warning("scipy not installed — mean_variance/risk_parity unavailable")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def equal_weight(self, symbols: list[str]) -> PortfolioWeights:
        """Equal-weight baseline portfolio."""
        n = len(symbols)
        w = 1.0 / n if n > 0 else 0.0
        return PortfolioWeights(
            symbols=symbols,
            weights=[w] * n,
            method="equal",
        )

    def risk_parity(self, returns: pd.DataFrame) -> PortfolioWeights:
        """Risk parity: each asset contributes equal risk (volatility).

        Minimizes: Σ (w_i * σ_i - target)^2
        Subject to: Σ w_i = 1, w_i >= 0

        Args:
            returns: DataFrame with columns = symbols, rows = dates.

        Returns:
            PortfolioWeights with risk-parity weights.
        """
        symbols = list(returns.columns)
        n = len(symbols)

        if n == 0:
            return PortfolioWeights()

        vols = returns.std().values
        if np.any(vols == 0):
            logger.warning("Zero volatility detected, falling back to equal weight")
            return self.equal_weight(symbols)

        if not self._has_scipy:
            # ponytail: inverse-vol heuristic is a decent risk-parity proxy
            inv_vol = 1.0 / vols
            w = inv_vol / inv_vol.sum()
            return self._build_result(symbols, w.tolist(), "risk_parity", returns)

        from scipy.optimize import minimize

        target_risk = 1.0 / n

        def objective(w):
            portfolio_vols = w * vols
            return np.sum((portfolio_vols - target_risk) ** 2)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = [(0.0, 1.0) for _ in range(n)]
        x0 = np.ones(n) / n

        result = minimize(objective, x0, bounds=bounds, constraints=constraints,
                          method="SLSQP")
        if result.success:
            w = result.x
        else:
            logger.warning("Risk parity optimization failed: %s, fallback equal weight", result.message)
            inv_vol = 1.0 / vols
            w = inv_vol / inv_vol.sum()

        return self._build_result(symbols, w.tolist(), "risk_parity", returns)

    def mean_variance(
        self,
        returns: pd.DataFrame,
        target_return: Optional[float] = None,
    ) -> PortfolioWeights:
        """Mean-Variance optimization (Markowitz).

        Maximize Sharpe ratio: (w'μ) / sqrt(w'Σ w)
        Subject to: Σ w_i = 1, w_i >= 0

        Args:
            returns: DataFrame with columns = symbols, rows = dates.
            target_return: Optional target return for efficient frontier.
        """
        symbols = list(returns.columns)
        n = len(symbols)

        if n == 0:
            return PortfolioWeights()

        mu = returns.mean().values * 252  # Annualized
        sigma = returns.cov().values * 252  # Annualized

        if not self._has_scipy:
            # ponytail: equal-weight is the simplest mean-variance proxy
            logger.warning("scipy unavailable for mean-variance, using equal weight")
            return self.equal_weight(symbols)

        from scipy.optimize import minimize

        def neg_sharpe(w):
            port_return = np.dot(w, mu)
            port_vol = np.sqrt(np.dot(w.T, np.dot(sigma, w)))
            if port_vol == 0:
                return 1e9  # Penalize zero vol
            return -(port_return / port_vol)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = [(0.0, 0.4) for _ in range(n)]  # Max 40% per asset
        x0 = np.ones(n) / n

        result = minimize(neg_sharpe, x0, bounds=bounds, constraints=constraints,
                          method="SLSQP")
        if result.success:
            w = result.x
        else:
            logger.warning("Mean-variance optimization failed, fallback equal weight")
            w = np.ones(n) / n

        return self._build_result(symbols, w.tolist(), "mean_variance", returns)

    def black_litterman(
        self,
        returns: pd.DataFrame,
        market_caps: Optional[pd.Series] = None,
        views: Optional[dict[str, float]] = None,
        view_confidences: Optional[dict[str, float]] = None,
        tau: float = 0.05,
    ) -> PortfolioWeights:
        """Black-Litterman model: blend market equilibrium with investor views.

        Π = δ Σ w_mkt (implied equilibrium returns)
        E(R) = [(τΣ)^-1 + P'Ω^-1 P]^-1 [(τΣ)^-1 Π + P'Ω^-1 Q]

        Args:
            returns: Historical returns DataFrame.
            market_caps: Market capitalization for each symbol (equilibrium weights).
            views: Investor views dict {symbol: expected_excess_return}.
            view_confidences: Confidence in each view {symbol: 0-1}.
            tau: Uncertainty scaling parameter (default 0.05).

        Returns:
            PortfolioWeights from Black-Litterman posterior.
        """
        symbols = list(returns.columns)
        n = len(symbols)

        if n == 0:
            return PortfolioWeights()

        mu = returns.mean().values * 252
        sigma = returns.cov().values * 252

        # Market equilibrium weights
        if market_caps is not None:
            w_mkt = market_caps.reindex(symbols).fillna(0).values
            if w_mkt.sum() > 0:
                w_mkt = w_mkt / w_mkt.sum()
            else:
                w_mkt = np.ones(n) / n
        else:
            w_mkt = np.ones(n) / n

        # Implied equilibrium returns: Π = δ Σ w_mkt
        delta = 2.5  # Risk aversion coefficient
        pi = delta * np.dot(sigma, w_mkt)

        if not views or not self._has_scipy:
            # No views → equilibrium = market cap weights
            return self._build_result(symbols, w_mkt.tolist(), "black_litterman", returns)

        # Apply investor views
        # P: pick matrix (k × n), Q: view vector (k × 1), Ω: confidence diagonal
        view_symbols = list(views.keys())
        k = len(view_symbols)

        P = np.zeros((k, n))
        Q = np.zeros(k)
        omega = np.zeros((k, k))

        for i, sym in enumerate(view_symbols):
            if sym in symbols:
                j = symbols.index(sym)
                P[i, j] = 1.0
                Q[i] = views[sym]
                conf = (view_confidences or {}).get(sym, 0.5)
                # Ω = diag(P Σ P' * (1-confidence)/confidence * tau)
                omega[i, i] = np.dot(P[i], np.dot(sigma, P[i])) * (1.0 - conf) / max(conf, 0.01) * tau

        # Posterior: E(R) = [(τΣ)^-1 + P'Ω^-1 P]^-1 [(τΣ)^-1 Π + P'Ω^-1 Q]
        tau_sigma_inv = np.linalg.inv(tau * sigma)
        omega_inv = np.linalg.inv(omega)

        posterior_cov_inv = tau_sigma_inv + np.dot(P.T, np.dot(omega_inv, P))
        posterior_mean = np.dot(
            np.linalg.inv(posterior_cov_inv),
            np.dot(tau_sigma_inv, pi) + np.dot(P.T, np.dot(omega_inv, Q)),
        )

        # Mean-variance optimization with posterior returns
        from scipy.optimize import minimize

        def neg_sharpe(w):
            port_return = np.dot(w, posterior_mean)
            port_vol = np.sqrt(np.dot(w.T, np.dot(sigma, w)))
            if port_vol == 0:
                return 1e9
            return -(port_return / port_vol)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = [(0.0, 0.4) for _ in range(n)]
        x0 = w_mkt.copy()

        result = minimize(neg_sharpe, x0, bounds=bounds, constraints=constraints,
                          method="SLSQP")
        w = result.x if result.success else w_mkt

        return self._build_result(symbols, w.tolist(), "black_litterman", returns)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_result(
        self,
        symbols: list[str],
        weights: list[float],
        method: str,
        returns: pd.DataFrame,
    ) -> PortfolioWeights:
        """Compute expected return/risk/Sharpe from weights."""
        mu = returns.mean().values * 252
        sigma = returns.cov().values * 252

        w = np.array(weights)
        exp_ret = float(np.dot(w, mu))
        exp_risk = float(np.sqrt(np.dot(w.T, np.dot(sigma, w))))
        sharpe = exp_ret / exp_risk if exp_risk > 0 else 0.0

        return PortfolioWeights(
            symbols=symbols,
            weights=[round(x, 4) for x in weights],
            method=method,
            expected_return=round(exp_ret, 4),
            expected_risk=round(exp_risk, 4),
            sharpe_ratio=round(sharpe, 4),
        )
