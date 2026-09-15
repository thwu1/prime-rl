"""
Unidentifiable binomial model for parallel tempering benchmarking.

Model:
    p1 ~ Uniform(0, 1)
    p2 ~ Uniform(0, 1)
    n_successes ~ Binomial(n_trials, p1 * p2)

This over-parameterized model creates a challenging posterior that concentrates
on the curve p1*p2 = k/n, making standard MCMC mixing extremely poor.
"""

import math


class UnidentifiableBinomial:
    def __init__(self, n_trials=100, n_successes=50):
        self.n_trials = n_trials
        self.n_successes = n_successes
        self._log_binom_coeff = (
            math.lgamma(n_trials + 1)
            - math.lgamma(n_successes + 1)
            - math.lgamma(n_trials - n_successes + 1)
        )

    def log_likelihood(self, p1, p2):
        """Log likelihood: log Binomial(n_successes | n_trials, p1*p2)."""
        p = p1 * p2
        if p <= 0.0 or p >= 1.0:
            return float('-inf')
        k = self.n_successes
        n = self.n_trials
        return self._log_binom_coeff + k * math.log(p) + (n - k) * math.log(1.0 - p)

    def log_prior(self, p1, p2):
        """Log prior: Uniform(0,1) x Uniform(0,1)."""
        if 0.0 < p1 < 1.0 and 0.0 < p2 < 1.0:
            return 0.0
        return float('-inf')

    def log_joint(self, p1, p2):
        """Log joint = log prior + log likelihood."""
        lp = self.log_prior(p1, p2)
        if not math.isfinite(lp):
            return float('-inf')
        return lp + self.log_likelihood(p1, p2)
