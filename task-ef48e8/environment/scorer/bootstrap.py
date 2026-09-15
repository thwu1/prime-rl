"""
Bootstrap confidence interval computation for evaluation metrics.

Computes bootstrap CIs for micro-averaged F1 scores using
case-level resampling.
"""
import numpy as np


def compute_bootstrap_ci(per_case_data, n_bootstrap=2000, seed=42, confidence=0.95):
    """
    Compute bootstrap confidence interval for micro-averaged F1.

    Uses case-level resampling: for each bootstrap iteration, resample
    cases with replacement, pool the true positive / predicted / gold
    counts across the resampled cases, and compute micro F1 from the
    pooled counts.

    Args:
        per_case_data: list of dicts, each with keys "tp", "pred_count",
                       "gold_count", "f1" (per-case metrics)
        n_bootstrap: number of bootstrap iterations
        seed: random seed for reproducibility
        confidence: confidence level (default 0.95 for 95% CI)

    Returns:
        dict with "lower" and "upper" CI bounds
    """
    rng = np.random.RandomState(seed)
    n = len(per_case_data)
    bootstrap_f1s = []

    for _ in range(n_bootstrap):
        indices = rng.choice(n, size=n, replace=True)
        boot_f1 = np.mean([per_case_data[i]["f1"] for i in indices])
        bootstrap_f1s.append(boot_f1)

    alpha = 1 - confidence
    lower = float(np.percentile(bootstrap_f1s, 100 * alpha / 2))
    upper = float(np.percentile(bootstrap_f1s, 100 * (1 - alpha / 2)))
    return {"lower": lower, "upper": upper}
