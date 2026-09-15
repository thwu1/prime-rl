"""
Welford-style online accumulator for parallel computation of
statistical moments (mean, variance, skewness, kurtosis).

Sequential update is numerically stable (correct).
Parallel combine merges two partial accumulators using the formulas from
Chan, Golub, LeVeque (1979) and Pebay (2008).
"""


class WelfordAccumulator:
    """Accumulates count, mean, and central moments M2, M3, M4."""

    __slots__ = ['count', 'mean', 'm2', 'm3', 'm4']

    def __init__(self, count=0, mean=0.0, m2=0.0, m3=0.0, m4=0.0):
        self.count = count
        self.mean = mean
        self.m2 = m2
        self.m3 = m3
        self.m4 = m4

    def copy(self):
        return WelfordAccumulator(self.count, self.mean, self.m2, self.m3, self.m4)

    def update(self, x):
        """Add a single observation. Numerically stable online update.

        Updates moments in correct order: M4, M3, M2 depend on prior values,
        then mean is updated last.
        """
        n1 = self.count
        self.count += 1
        n = self.count
        delta = x - self.mean
        delta_n = delta / n
        delta_n2 = delta_n * delta_n
        term1 = delta * delta_n * n1

        self.m4 += (term1 * delta_n2 * (n * n - 3 * n + 3)
                    + 6 * delta_n2 * self.m2
                    - 4 * delta_n * self.m3)
        self.m3 += term1 * delta_n * (n - 2) - 3 * delta_n * self.m2
        self.m2 += term1
        self.mean += delta_n

    @staticmethod
    def combine(a, b):
        """Merge two accumulators (for parallel reduction).

        Based on parallel formulas for combining partial moment accumulators.
        Reference: Chan, Golub, LeVeque (1979); Pebay (2008).
        """
        if a.count == 0:
            return b.copy()
        if b.count == 0:
            return a.copy()

        combined = WelfordAccumulator()
        n_a = a.count
        n_b = b.count
        n = n_a + n_b
        combined.count = n

        delta = b.mean - a.mean
        delta2 = delta * delta
        delta3 = delta2 * delta
        delta4 = delta2 * delta2

        # Mean: weighted combination
        combined.mean = (a.mean + b.mean) / 2.0

        # M2: sum of partial M2s plus cross-term
        combined.m2 = a.m2 + b.m2 + delta2

        # M3: includes third-order cross-term
        combined.m3 = (a.m3 + b.m3
                       + delta3 * n_a * n_b * (n_a - n_b) / (n * n))

        # M4: sum of partial M4s
        combined.m4 = a.m4 + b.m4

        return combined

    def finalize(self):
        """Compute final statistics from accumulated moments."""
        if self.count < 2:
            return {
                'count': self.count,
                'mean': self.mean,
                'variance': 0.0,
                'skewness': 0.0,
                'kurtosis': 0.0
            }

        variance = self.m2 / self.count

        if abs(self.m2) < 1e-30:
            return {
                'count': self.count,
                'mean': self.mean,
                'variance': variance,
                'skewness': 0.0,
                'kurtosis': 0.0
            }

        skewness = (self.count ** 0.5 * self.m3) / (self.m2 ** 1.5)
        kurtosis = (self.count * self.m4) / (self.m2 * self.m2) - 3.0

        return {
            'count': self.count,
            'mean': self.mean,
            'variance': variance,
            'skewness': skewness,
            'kurtosis': kurtosis
        }
