
"""GARCH(1,1) and GJR-GARCH(1,1) volatility models.

Implements:
  - GARCH(1,1) parameter management, conditional variance updating, multi-step
    forecasting, and maximum-likelihood estimation via grid search with gradient ascent.
  - GJR-GARCH(1,1) with leverage effect (asymmetric response to negative returns).
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class GarchParams:
    """Parameters for a GARCH(1,1) model: sigma^2_t = omega + alpha*r^2_{t-1} + beta*sigma^2_{t-1}."""
    omega: float
    alpha: float
    beta: float

    def is_stationary(self) -> bool:
        return self.alpha + self.beta < 1.0

    def long_run_variance(self) -> float:
        if self.alpha + self.beta >= 1.0:
            return float('inf')
        return self.omega / (1.0 - self.alpha - self.beta)

    def persistence(self) -> float:
        return self.alpha + self.beta

    def shock_half_life(self) -> float:
        p = self.persistence()
        if p <= 0.0 or p >= 1.0:
            return float('nan')
        return -math.log(2.0) / math.log(p)


class GarchState:
    """Running state of a GARCH(1,1) process."""

    def __init__(self, params: GarchParams, initial_variance: float):
        self.params = params
        self.conditional_variance = initial_variance
        self.last_return = 0.0

    def update(self, return_t: float) -> None:
        if not math.isfinite(return_t):
            return
        new_var = (self.params.omega
                   + self.params.alpha * return_t ** 2
                   + self.params.beta * self.conditional_variance)
        self.conditional_variance = max(new_var, 1e-10)
        self.last_return = return_t

    def current_vol_annualized(self) -> float:
        return math.sqrt(self.conditional_variance * 252.0)

    def forecast(self, h: int) -> float:
        lr = self.params.long_run_variance()
        if math.isinf(lr):
            return self.conditional_variance
        p_h = self.params.persistence() ** h
        return lr + p_h * (self.conditional_variance - lr)

    def forecast_vol_annualized(self, h: int) -> float:
        return math.sqrt(self.forecast(h) * 252.0)

    def var_1day(self, z_score: float, position_value: float) -> float:
        return z_score * math.sqrt(self.conditional_variance) * position_value


class GarchEstimator:
    """Maximum-likelihood estimator for GARCH(1,1) via grid search + gradient ascent."""

    @staticmethod
    def fit(returns: List[float]) -> Optional[Tuple[GarchParams, float]]:
        clean = [r for r in returns if math.isfinite(r)]
        if len(clean) < 50:
            return None

        n = len(clean)
        sample_var = sum(r * r for r in clean) / n

        best_ll = float('-inf')
        best_params = GarchParams(omega=sample_var * 0.05, alpha=0.05, beta=0.90)

        # Coarse grid search: omega determined analytically from stationarity
        alpha_grid = [i * 0.01 for i in range(2, 21)]   # 0.02 to 0.20
        beta_grid = [i * 0.01 for i in range(75, 96)]    # 0.75 to 0.95

        for a in alpha_grid:
            for b in beta_grid:
                if a + b >= 0.999:
                    continue
                omega = sample_var * (1.0 - a - b)
                if omega <= 0:
                    continue
                p = GarchParams(omega=omega, alpha=a, beta=b)
                ll = GarchEstimator._log_likelihood(clean, p)
                if ll > best_ll:
                    best_ll = ll
                    best_params = p

        # Local refinement around the best grid point
        base_a, base_b = best_params.alpha, best_params.beta
        deltas = [-0.005, -0.003, -0.002, -0.001, 0.0, 0.001, 0.002, 0.003, 0.005]
        for da in deltas:
            for db in deltas:
                a = base_a + da
                b = base_b + db
                if a <= 0.001 or b <= 0.001 or a + b >= 0.999:
                    continue
                omega = sample_var * (1.0 - a - b)
                if omega <= 0:
                    continue
                p = GarchParams(omega=omega, alpha=a, beta=b)
                ll = GarchEstimator._log_likelihood(clean, p)
                if ll > best_ll:
                    best_ll = ll
                    best_params = p

        return (best_params, best_ll)

    @staticmethod
    def _log_likelihood(returns: List[float], params: GarchParams) -> float:
        n = len(returns)
        sample_var = sum(r * r for r in returns) / n
        sigma2 = sample_var
        ll = 0.0
        for r in returns:
            sigma2 = params.omega + params.alpha * r * r + params.beta * sigma2
            sigma2 = max(sigma2, 1e-12)
            ll += -0.5 * (math.log(sigma2) + r * r / sigma2)
        return ll / n


@dataclass
class GjrGarchParams:
    """GJR-GARCH(1,1): sigma^2_t = omega + (alpha + gamma*I[r<0])*r^2 + beta*sigma^2."""
    omega: float
    alpha: float
    beta: float
    gamma: float  # leverage coefficient

    def is_stationary(self) -> bool:
        return self.alpha + self.beta + self.gamma / 2.0 < 1.0

    def long_run_variance(self) -> float:
        denom = 1.0 - self.alpha - self.beta - self.gamma / 2.0
        if denom <= 0.0:
            return float('inf')
        return self.omega / denom

    def persistence(self) -> float:
        return self.alpha + self.beta + self.gamma / 2.0


class GjrGarchState:
    """Running state of a GJR-GARCH(1,1) process."""

    def __init__(self, params: GjrGarchParams, initial_variance: float):
        self.params = params
        self.conditional_variance = initial_variance
        self.last_return = 0.0

    def update(self, return_t: float) -> None:
        leverage = 1.0 if return_t < 0.0 else 0.0
        new_var = (self.params.omega
                   + (self.params.alpha + self.params.gamma * leverage) * return_t ** 2
                   + self.params.beta * self.conditional_variance)
        self.conditional_variance = max(new_var, 1e-10)
        self.last_return = return_t

    def current_vol_annualized(self) -> float:
        return math.sqrt(self.conditional_variance * 252.0)

    def forecast(self, h: int) -> float:
        lr = self.params.long_run_variance()
        if math.isinf(lr):
            return self.conditional_variance
        p_h = self.params.persistence() ** h
        return lr + p_h * (self.conditional_variance - lr)
