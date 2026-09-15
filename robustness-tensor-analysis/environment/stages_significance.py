"""Pairwise permutation significance tests.

For each unordered pair of models, computes paired differences of perturbation
effects across all non-default perturbations and tasks, then uses a sign-flip
permutation test to assess statistical significance.
"""
import numpy as np
from db import load_model_data, get_models, get_total_rollouts, get_perturbation_names


def run(prior_results, config, taxonomy):
    """Paired sign-flip permutation test for each model pair.

    For each pair (m1, m2) ordered alphabetically:
    - Compute d[p,t] = (rate[m1,p,t]-rate[m1,0,t]) - (rate[m2,p,t]-rate[m2,0,t])
      for all non-default perturbations p and tasks t
    - Test statistic T = mean(d)
    - Permutation test: for B iterations, randomly flip signs of d values
      using seeded RNG, compute T_perm = mean(flipped_d)
    - p_value = (1 + count(|T_perm| >= |T_obs|)) / (1 + B)

    Returns dict: "m1_vs_m2" -> {"statistic": float, "p_value": float}
    """
    models = sorted(get_models())
    total = get_total_rollouts()
    p_names = get_perturbation_names()
    non_default_pids = sorted([pid for pid in p_names.keys() if pid != 0])

    B = config.get("bootstrap_samples", 10000)
    seed = config["seed"]

    sample_data = load_model_data(models[0])
    task_ids = sorted(set(t for (_, t) in sample_data.keys()))

    all_data = {m: load_model_data(m) for m in models}

    results = {}
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            m1, m2 = models[i], models[j]

            d = []
            for p_id in non_default_pids:
                for t_id in task_ids:
                    eff1 = (all_data[m1][(p_id, t_id)] - all_data[m1][(0, t_id)]) / total
                    eff2 = (all_data[m2][(p_id, t_id)] - all_data[m2][(0, t_id)]) / total
                    d.append(eff1 - eff2)

            d = np.array(d)
            T_obs = np.mean(d)

            rng = np.random.RandomState(seed)
            count = 0
            for _ in range(B):
                signs = rng.choice([-1, 1], size=len(d))
                T_perm = np.mean(d * signs)
                if abs(T_perm) >= abs(T_obs):
                    count += 1

            p_value = (1 + count) / (1 + B)

            key = f"{m1}_vs_{m2}"
            results[key] = {
                "statistic": float(T_obs),
                "p_value": float(p_value)
            }

    return results
