"""GARCH(1,1) volatility model for conditional variance estimation."""

import math


class GarchParams:
    def __init__(self, omega, alpha, beta):
        self.omega = omega
        self.alpha = alpha
        self.beta = beta

    def is_stationary(self):
        return self.alpha + self.beta < 1.0

    def long_run_variance(self):
        denom = 1.0 - self.alpha - self.beta
        if denom <= 0:
            return float('inf')
        return self.omega / denom

    def persistence(self):
        return self.alpha + self.beta

    def shock_half_life(self):
        p = self.persistence()
        if p <= 0 or p >= 1:
            return float('nan')
        return -math.log(2) / math.log(p)


class GarchState:
    def __init__(self, params, initial_variance):
        self.params = params
        self.conditional_variance = initial_variance
        self.last_return = 0.0

    def update(self, return_t):
        if not math.isfinite(return_t):
            return
        p = self.params
        new_var = p.omega + p.beta * return_t ** 2 + p.alpha * self.conditional_variance
        self.conditional_variance = max(new_var, 1e-10)
        self.last_return = return_t

    def forecast(self, h):
        lr = self.params.long_run_variance()
        if not math.isfinite(lr):
            return self.conditional_variance
        p_h = self.params.persistence() ** h
        return lr + p_h * (self.conditional_variance - lr)

    def current_vol_annualized(self):
        return math.sqrt(self.conditional_variance * 252)

    def var_1day(self, z_score, position_value):
        return z_score * math.sqrt(self.conditional_variance) * position_value


class GarchEstimator:
    @staticmethod
    def log_likelihood(returns, params):
        n = len(returns)
        if n == 0:
            return float('-inf')
        sample_var = sum(r * r for r in returns) / n
        sigma2 = sample_var
        ll = 0.0
        for r in returns:
            sigma2 = params.omega + params.alpha * r * r + params.beta * sigma2
            sigma2 = max(sigma2, 1e-12)
            ll += -0.5 * (math.log(sigma2) + r * r / sigma2)
        return ll / n

    @staticmethod
    def fit(returns):
        clean = [r for r in returns if math.isfinite(r)]
        if len(clean) < 50:
            return None

        n = len(clean)
        sample_var = sum(r * r for r in clean) / n

        best_ll = float('-inf')
        best_params = None

        alpha_grid = [0.03, 0.05, 0.08, 0.10, 0.12, 0.15]
        beta_grid = [0.80, 0.85, 0.87, 0.90, 0.92, 0.94]

        for alpha in alpha_grid:
            for beta in beta_grid:
                if alpha + beta >= 0.999:
                    continue
                omega = sample_var * (1 - alpha - beta)
                if omega <= 0:
                    continue
                p = GarchParams(omega, alpha, beta)
                ll = GarchEstimator.log_likelihood(clean, p)
                if ll > best_ll:
                    best_ll = ll
                    best_params = p

        if best_params is None:
            return None

        cur_omega = best_params.omega
        cur_alpha = best_params.alpha
        cur_beta = best_params.beta
        eps = 1e-6
        lr = 1e-5

        for _ in range(200):
            p = GarchParams(cur_omega, cur_alpha, cur_beta)
            ll = GarchEstimator.log_likelihood(clean, p)

            pa = GarchParams(cur_omega, cur_alpha + eps, cur_beta)
            pb = GarchParams(cur_omega, cur_alpha, cur_beta + eps)
            po = GarchParams(cur_omega + eps, cur_alpha, cur_beta)

            grad_a = (GarchEstimator.log_likelihood(clean, pa) - ll) / eps
            grad_b = (GarchEstimator.log_likelihood(clean, pb) - ll) / eps
            grad_o = (GarchEstimator.log_likelihood(clean, po) - ll) / eps

            cur_alpha = max(1e-6, min(0.5, cur_alpha + lr * grad_a))
            cur_beta = max(1e-6, cur_beta + lr * grad_b)
            cur_omega = max(1e-12, cur_omega + lr * grad_o)

            if cur_alpha + cur_beta >= 0.999:
                s = 0.998 / (cur_alpha + cur_beta)
                cur_alpha *= s
                cur_beta *= s

        final = GarchParams(cur_omega, cur_alpha, cur_beta)
        final_ll = GarchEstimator.log_likelihood(clean, final)
        return (final, final_ll)
