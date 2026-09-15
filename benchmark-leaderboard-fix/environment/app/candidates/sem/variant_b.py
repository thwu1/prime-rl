"""Standard error of the mean -- Bessel-corrected sample formula."""
from math import sqrt


def compute_sem(successes, total):
    """Compute SEM with Bessel's correction (divides by n-1).

    SEM = sqrt(p * (1-p) / (n-1))
    """
    if total <= 1:
        return 0.0
    p = successes / total
    if p == 0.0 or p == 1.0:
        return 0.0
    return sqrt(p * (1.0 - p) / (total - 1))
