"""Wilson score confidence intervals for benchmark success rates."""
import math
from db import load_model_data, get_models, get_total_rollouts

Z_95 = 1.959963984540054


def run(prior_results, config, taxonomy):
    """Compute Wilson score 95% CI for every (model, perturbation, task) cell."""
    models = get_models()
    total = get_total_rollouts()
    intervals = {}

    for model in models:
        data = load_model_data(model)
        intervals[model] = {}
        for (p_id, t_id), successes in data.items():
            p_key = str(p_id)
            t_key = str(t_id)
            if p_key not in intervals[model]:
                intervals[model][p_key] = {}

            n = total
            p_hat = successes / n
            z = Z_95
            denom = 1 + z / n
            center = p_hat + z ** 2 / (2 * n)
            spread = z * math.sqrt(
                p_hat * (1 - p_hat) / n + z ** 2 / (4 * n ** 2)
            )
            ci_lower = (center - spread) / denom
            ci_upper = (center + spread) / denom

            intervals[model][p_key][t_key] = {
                "rate": p_hat,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper
            }

    return intervals
