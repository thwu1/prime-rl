
"""
Anytime-valid confidence sequences using mixture martingale bounds.

Based on Howard, Ramdas, McAuliffe, Sekhon (2022).
Uses Welford's algorithm for running variance and the
GammaExponentialMixture bound for radius computation.
"""

import numpy as np
from .martingales import GammaExponentialMixture


class ConfidenceSequence:
    def __init__(self, alpha=0.05, v_opt=100, c=1.0, alpha_opt=0.05):
        self.alpha = alpha
        self.v_opt = v_opt
        self.c = c
        self.alpha_opt = alpha_opt
        self.mixture = GammaExponentialMixture(v_opt, alpha_opt / 2, c)
        self.reset()

    def reset(self):
        self.n = 0
        self.sum_x = 0.0
        self.mean = 0.0
        self.M2 = 0.0
        self.var = 0.0

    def update(self, x):
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.M2 += delta * delta2

        if self.n > 1:
            self.var = self.M2 / (self.n - 1)

        intrinsic_time = self.n * self.var if self.n > 1 else float(self.n)

        log_threshold = np.log(2.0 / self.alpha)
        bound_value = self.mixture.bound(intrinsic_time, log_threshold)

        radius = bound_value / self.n
        return (self.mean - radius, self.mean + radius)
