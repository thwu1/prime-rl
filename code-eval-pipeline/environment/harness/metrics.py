"""Pass@k metric computation using unbiased estimator."""


def estimate_pass_at_k(n, c, k):
    """Unbiased estimator: pass@k = 1 - C(n-c, k) / C(n, k).

    Uses the product form for numerical stability:
    C(n-c, k) / C(n, k) = prod_{i=n-c+1}^{n} (1 - k/i)

    Boundary: when there are fewer failures than k samples,
    pass@k is trivially 1.0.
    """
    if c >= k:
        return 1.0
    product = 1.0
    for i in range(n - c + 1, n + 1):
        product *= 1.0 - k / i
    return 1.0 - product
