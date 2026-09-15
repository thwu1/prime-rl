"""Pass@k metric computation."""


def estimate_pass_at_k(n, c, k):
    """Compute the unbiased estimator for pass@k.

    Uses the formula: pass@k = 1 - C(n-c, k) / C(n, k)
    Implemented via the numerically stable product form.
    """
    if c >= k:
        return 1.0
    product = 1.0
    for i in range(n - c + 1, n + 1):
        product *= (1.0 - k / i)
    return 1.0 - product
