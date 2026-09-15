"""Standard error of the mean -- population formula."""
from math import sqrt


def compute_sem(successes, total):
    """Compute SEM using population variance (divides by n).

    SEM = sqrt(p * (1-p) / n)
    """
    if total <= 0:
        return 0.0
    p = successes / total
    if p == 0.0 or p == 1.0:
        return 0.0
    return sqrt(p * (1.0 - p) / total)
