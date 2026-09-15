"""pass@k via Bernoulli power rule approximation."""


def compute_pass_at_k(n, c, k):
    """Estimate pass@k treating each draw as an independent Bernoulli trial.

    pass@k = 1 - (1 - c/n)^k

    Assumes independent draws with replacement from an infinite population.
    """
    if n <= 0 or k <= 0:
        return 0.0
    if c <= 0:
        return 0.0
    if c >= n:
        return 1.0
    p = c / n
    return 1.0 - (1.0 - p) ** k
