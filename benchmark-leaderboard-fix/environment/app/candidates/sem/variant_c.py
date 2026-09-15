"""Cluster-robust standard error with design-effect correction."""
from math import sqrt


def compute_sem(successes, total):
    """Compute cluster-robust SE with ICC-based design effect.

    Applies a design-effect correction factor:
    DEFF = 1 + (avg_cluster_size - 1) * ICC
    SEM = sqrt(p * (1-p) * DEFF / (n-1))

    Assumes ICC ~ 0.05 and average cluster size of 5 runs per task.
    """
    if total <= 1:
        return 0.0
    p = successes / total
    if p == 0.0 or p == 1.0:
        return 0.0
    icc = 0.05
    avg_cluster_size = 5
    deff = 1 + (avg_cluster_size - 1) * icc
    return sqrt(p * (1.0 - p) * deff / (total - 1))
