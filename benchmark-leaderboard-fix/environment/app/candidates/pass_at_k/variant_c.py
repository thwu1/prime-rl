"""pass@k via Bayesian Beta posterior estimation."""
from math import lgamma, exp


def compute_pass_at_k(n, c, k):
    """Estimate pass@k using Beta(c+1, n-c+1) posterior.

    Computes E[(1-p)^k] under the Beta posterior analytically:
    E[(1-p)^k] = prod_{i=0}^{k-1} (b+i) / (a+b+i)
    where a = c+1, b = n-c+1.

    Then pass@k = 1 - E[(1-p)^k].
    """
    if n <= 0 or k <= 0:
        return 0.0
    if c < 0:
        c = 0
    if c > n:
        c = n
    a = c + 1
    b = n - c + 1
    # E[(1-p)^k] under Beta(a, b) = prod_{i=0}^{k-1} (b+i)/(a+b+i)
    ratio = 1.0
    for i in range(k):
        ratio *= (b + i) / (a + b + i)
    return 1.0 - ratio
