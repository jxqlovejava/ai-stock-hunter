"""GARCH(1,1) conditional volatility indicator with MLE fitting."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _garch_recursion(
    returns: np.ndarray, omega: float, alpha: float, beta: float,
) -> np.ndarray:
    """Run GARCH(1,1) variance recursion.

    sigma2_t = omega + alpha * r_{t-1}^2 + beta * sigma2_{t-1}
    """
    n = len(returns)
    sigma2 = np.empty(n)
    # Seed with unconditional variance
    sigma2[0] = omega / (1 - alpha - beta)
    for t in range(1, n):
        sigma2[t] = omega + alpha * returns[t - 1] ** 2 + beta * sigma2[t - 1]
    return sigma2


def _garch_neg_loglik(
    params: np.ndarray, returns: np.ndarray,
) -> float:
    """Negative log-likelihood for GARCH(1,1) under Gaussian assumption."""
    omega, alpha, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
        return 1e10
    sigma2 = _garch_recursion(returns, omega, alpha, beta)
    # Guard against non-positive variance
    sigma2 = np.maximum(sigma2, 1e-20)
    ll = -0.5 * np.sum(np.log(sigma2) + returns**2 / sigma2)
    return -ll


def _fit_garch_mle(returns: np.ndarray) -> tuple[float, float, float]:
    """Fit GARCH(1,1) parameters via MLE using scipy."""
    try:
        from scipy.optimize import minimize
    except ImportError as e:
        raise ImportError(
            "scipy is required for GARCH MLE fitting. "
            "Install with: pip install open-xquant[scipy]"
        ) from e

    # Initial guesses
    x0 = np.array([np.var(returns) * 0.05, 0.05, 0.90])
    bounds = [(1e-10, None), (1e-10, 0.9999), (1e-10, 0.9999)]
    constraints = {"type": "ineq", "fun": lambda p: 0.9999 - p[1] - p[2]}

    result = minimize(
        _garch_neg_loglik,
        x0,
        args=(returns,),
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )

    omega, alpha, beta = result.x
    return float(omega), float(alpha), float(beta)


class GarchVolatility:
    """GARCH(1,1) conditional volatility.

    sigma^2_t = omega + alpha * r_{t-1}^2 + beta * sigma^2_{t-1}

    If omega, alpha, beta are not provided, they are fitted via MLE
    (requires scipy). If all three are provided, the recursion is
    computed directly without fitting.
    """

    name = "GarchVolatility"
    formula = r"\sigma^2_t = \omega + \alpha\,r_{t-1}^2 + \beta\,\sigma^2_{t-1}"

    def compute(
        self,
        mktdata: pd.DataFrame,
        column: str = "close",
        omega: float | None = None,
        alpha: float | None = None,
        beta: float | None = None,
    ) -> pd.Series:
        """Return conditional volatility sigma_t series.

        Parameters
        ----------
        mktdata : pd.DataFrame
            Market data with a price column.
        column : str
            Column name for prices (default "close").
        omega, alpha, beta : float or None
            GARCH(1,1) parameters. If any is None, all are fitted via MLE.
        """
        log_returns = np.log(mktdata[column]).diff()
        r = log_returns.to_numpy(dtype=float)
        n = len(r)

        result = np.empty(n)
        result[0] = np.nan

        if n < 3:
            result[1:] = np.nan
            return pd.Series(result, index=mktdata.index, name=self.name)

        # Returns for fitting/recursion (skip first NaN)
        returns = r[1:]

        if omega is None or alpha is None or beta is None:
            omega_f, alpha_f, beta_f = _fit_garch_mle(returns)
        else:
            omega_f, alpha_f, beta_f = omega, alpha, beta

        sigma2 = _garch_recursion(returns, omega_f, alpha_f, beta_f)
        result[1:] = np.sqrt(sigma2)

        return pd.Series(result, index=mktdata.index, name=self.name)
