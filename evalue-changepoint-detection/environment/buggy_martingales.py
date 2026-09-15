
"""
Mixture supermartingale implementations for sequential testing.

Based on:
- Howard, Ramdas, McAuliffe, Sekhon (2022): Time-uniform confidence sequences
- Vovk, Wang (2024): Merging sequential e-values via martingales
"""

import numpy as np
from scipy import special, stats, optimize


class TwoSidedNormalMixture:
    """Two-sided normal mixture supermartingale.

    log M(s,v) = 0.5 * log(rho/(v+rho)) + s^2 / (2*(v+rho))

    The GROW-optimal mixing parameter is:
        rho* = v_opt / (2*log(1/alpha) + log(1 + 2*log(1/alpha)))
    """

    def __init__(self, v_opt, alpha_opt):
        assert v_opt > 0
        assert 0 < alpha_opt < 1
        self.v_opt = v_opt
        self.alpha_opt = alpha_opt
        self.rho = self._best_rho(v_opt, alpha_opt)

    @staticmethod
    def _best_rho(v_opt, alpha_opt):
        log_inv_alpha = np.log(1.0 / alpha_opt)
        return v_opt / (2 * log_inv_alpha + np.log(2 * log_inv_alpha))

    def log_superMG(self, s, v):
        return 0.5 * np.log(self.rho / (v + self.rho)) + s * s / (2 * (v + self.rho))

    def s_upper_bound(self, v):
        return np.inf

    def bound(self, v, log_threshold):
        return np.sqrt(
            (v + self.rho) * (np.log(1 + v / self.rho) + 2 * log_threshold)
        )


class OneSidedNormalMixture:
    """One-sided normal mixture supermartingale.

    log M(s,v) = 0.5*log(4*rho/(v+rho)) + s^2/(2*(v+rho)) + log(Phi(s/sqrt(v+rho)))

    Uses rho = best_rho_two_sided(v_opt, 2*alpha_opt) for power concentration.
    """

    def __init__(self, v_opt, alpha_opt):
        assert v_opt > 0
        assert 0 < alpha_opt < 1
        self.v_opt = v_opt
        self.alpha_opt = alpha_opt
        self.rho = TwoSidedNormalMixture._best_rho(v_opt, 2 * alpha_opt)

    def log_superMG(self, s, v):
        sigma = np.sqrt(v + self.rho)
        return (
            0.5 * np.log(self.rho / (v + self.rho))
            + s * s / (2 * (v + self.rho))
            + np.log(stats.norm.cdf(s / sigma))
        )

    def s_upper_bound(self, v):
        return np.inf

    def bound(self, v, log_threshold):
        def root_fn(s):
            return self.log_superMG(s, v) - log_threshold

        s_upper = float(max(v, 1.0))
        for _ in range(50):
            if root_fn(s_upper) > 0:
                break
            s_upper *= 2

        if root_fn(s_upper) < 0:
            return s_upper

        return optimize.bisect(root_fn, 0.0, s_upper, xtol=2**-40)


def log_beta(a, b):
    return special.gammaln(a) + special.gammaln(b) - special.gammaln(a + b)


def log_incomplete_beta(a, b, x):
    if x == 1:
        return log_beta(a, b)
    val = special.betainc(a, b, x)
    if val <= 0:
        return -np.inf
    return np.log(val) + log_beta(a, b)


class BetaBinomialMixture:
    """Beta-binomial mixture supermartingale for proportion testing.

    Uses the regularized incomplete beta function I_x(a,b) from scipy.
    Null proportion p_0 = g/(g+h).
    """

    def __init__(self, g, h, v_opt, alpha_opt, is_one_sided=False):
        assert g > 0 and h > 0
        self.g = g
        self.h = h
        self.is_one_sided = is_one_sided
        self.r = self._optimal_r(v_opt, alpha_opt)
        self.normalizer = self._compute_normalizer()

    def _optimal_r(self, v_opt, alpha_opt):
        if self.is_one_sided:
            rho = TwoSidedNormalMixture._best_rho(v_opt, 2 * alpha_opt)
        else:
            rho = TwoSidedNormalMixture._best_rho(v_opt, alpha_opt)
        return max(rho - self.g * self.h, 1e-3 * self.g * self.h)

    def _compute_normalizer(self):
        x = self.h / (self.g + self.h) if self.is_one_sided else 1
        return log_incomplete_beta(
            self.r / (self.g * (self.g + self.h)),
            self.r / (self.h * (self.g + self.h)),
            x,
        )

    def log_superMG(self, s, v):
        g, h = self.g, self.h
        gh = g + h
        x = h / gh if self.is_one_sided else 1

        a_param = (self.r + v - g * s) / (g * gh)
        b_param = (self.r + v + h * s) / (h * gh)

        if a_param <= 0 or b_param <= 0:
            return -np.inf

        return (
            v / (g * h) * np.log(gh)
            - (v + h * s) / (h * gh) * np.log(g)
            - (v - g * s) / (g * gh) * np.log(h)
            + log_incomplete_beta(a_param, b_param, x)
            - self.normalizer
        )

    def s_upper_bound(self, v):
        return v / self.g

    def bound(self, v, log_threshold):
        def root_fn(s):
            return self.log_superMG(s, v) - log_threshold

        s_upper = self.s_upper_bound(v)
        if np.isinf(s_upper):
            s_upper = float(max(v, 1.0))
            for _ in range(50):
                if root_fn(s_upper) > 0:
                    break
                s_upper *= 2

        if root_fn(s_upper) < 0:
            return s_upper

        return optimize.bisect(root_fn, 0.0, s_upper, xtol=2**-40)


class GammaExponentialMixture:
    """Gamma-exponential mixture supermartingale.

    Uses the regularized lower incomplete gamma ratio P(a,x) from scipy.
    """

    def __init__(self, v_opt, alpha_opt, c):
        assert c > 0
        self.c = c
        self.rho = TwoSidedNormalMixture._best_rho(v_opt, 2 * alpha_opt)
        self.leading_constant = self._get_leading_constant()

    def _get_leading_constant(self):
        rho_c_sq = self.rho / (self.c * self.c)
        return (
            rho_c_sq * np.log(rho_c_sq)
            - special.gammaln(rho_c_sq)
            - np.log(special.gammainc(rho_c_sq, rho_c_sq))
        )

    def log_superMG(self, s, v):
        c_sq = self.c * self.c
        cs_v_csq = (self.c * s + v) / c_sq
        v_rho_csq = (v + self.rho) / c_sq

        return (
            self.leading_constant
            + special.gammaln(v_rho_csq)
            + np.log(special.gammainc(v_rho_csq, cs_v_csq + self.rho / c_sq))
            - v_rho_csq * np.log(cs_v_csq + self.rho / c_sq)
            + cs_v_csq
        )

    def s_upper_bound(self, v):
        return np.inf

    def bound(self, v, log_threshold):
        def root_fn(s):
            return self.log_superMG(s, v) - log_threshold

        s_upper = float(max(v, 1.0))
        for _ in range(50):
            if root_fn(s_upper) > 0:
                break
            s_upper *= 2

        if root_fn(s_upper) < 0:
            return s_upper

        return optimize.bisect(root_fn, 0.0, s_upper, xtol=2**-40)
