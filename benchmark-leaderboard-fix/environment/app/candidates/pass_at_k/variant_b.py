"""pass@k via exact combinatorial (hypergeometric) estimator."""
from math import comb


def compute_pass_at_k(n, c, k):
    """Compute the unbiased pass@k estimator.

    pass@k = 1 - C(n-c, k) / C(n, k)

    Based on hypergeometric sampling without replacement from
    the finite pool of n observed runs.
    """
    if n <= 0 or k <= 0:
        return 0.0
    if c < 0:
        c = 0
    if c > n:
        c = n
    if k > n:
        return 1.0 if c > 0 else 0.0
    denom = comb(n, k)
    if denom == 0:
        return 1.0 if c > 0 else 0.0
    return 1.0 - comb(n - c, k) / denom
