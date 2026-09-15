"""Perturbation effect matrix computation."""
from db import load_model_data, get_models, get_total_rollouts, get_perturbation_names


def run(prior_results, config, taxonomy):
    """Compute effect matrix E[m,p] = mean_t(rate[m,p,t] - rate[m,default,t]).

    For each model and non-default perturbation, computes the average
    difference in success rate across all tasks relative to the default
    (unperturbed) condition.
    """
    models = get_models()
    total = get_total_rollouts()
    p_names = get_perturbation_names()

    effect_matrix = {}
    for model in models:
        data = load_model_data(model)
        effects = {}

        task_ids = sorted(set(t for (_, t) in data.keys()))

        for p_id, p_name in p_names.items():
            if p_id == 0:
                continue
            diffs = []
            for t_id in task_ids:
                rate_p = data[(p_id, t_id)] / total
                rate_d = data[(0, t_id)] / total
                diffs.append(rate_p - rate_d)
            effects[p_name] = sum(diffs) / len(diffs)

        effect_matrix[model] = effects

    return effect_matrix
