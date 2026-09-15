"""Statistical metrics for evaluation quality assessment."""

import numpy as np


def compute_fleiss_kappa(scores_by_key, binary_ids, sample_ids, judge_ids):
    """Compute Fleiss' kappa for inter-rater reliability on binary criteria.

    Each (sample, binary_criterion) pair is treated as one subject.
    Each judge is one rater. The two categories are pass (>= 0.5)
    and fail (< 0.5).
    """
    n_raters = len(judge_ids)
    if n_raters < 2:
        return 0.0

    subjects = []
    total_pass = 0
    total_ratings = 0

    for sample_id in sample_ids:
        for crit_id in binary_ids:
            n_pass = 0
            n_total = 0
            for judge_id in judge_ids:
                key = (sample_id, judge_id, crit_id)
                if key in scores_by_key:
                    n_total += 1
                    if scores_by_key[key] >= 0.5:
                        n_pass += 1
            n_fail = n_total - n_pass
            subjects.append((n_pass, n_fail, n_total))
            total_pass += n_pass
            total_ratings += n_total

    if total_ratings == 0:
        return 0.0

    p_i_list = []
    for n_pass, n_fail, n_total in subjects:
        if n_total <= 1:
            p_i_list.append(0.0)
        else:
            p_i = (n_pass ** 2 + n_fail ** 2 - n_total) / (n_total * n_total)
            p_i_list.append(p_i)

    p_bar = sum(p_i_list) / len(p_i_list)

    p_pass = total_pass / total_ratings
    p_fail = 1.0 - p_pass
    p_e = p_pass ** 2 + p_fail ** 2

    if abs(1.0 - p_e) < 1e-12:
        return 0.0

    return (p_bar - p_e) / (1.0 - p_e)


def compute_bootstrap_ci(scores, seed, n_resamples):
    """Compute bootstrap 95% confidence interval for the mean score.

    Uses numpy's default_rng with the provided seed for reproducibility.
    Resamples with replacement and computes 2.5th/97.5th percentiles.
    """
    arr = np.array(scores)
    boot_means = []
    for i in range(n_resamples):
        rng = np.random.default_rng(seed)
        boot_sample = rng.choice(arr, size=len(arr), replace=True)
        boot_means.append(float(np.mean(boot_sample)))

    boot_means = np.array(boot_means)
    return float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5))
