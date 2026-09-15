"""Category-level robustness scoring.

For each model and perturbation category (both base and compound categories
defined in the taxonomy), computes a robustness score in [0,1] where:
- 1.0 = perfectly robust (no performance degradation from perturbations)
- 0.0 = maximally degraded

The score is based on the root-mean-square of perturbation effects within
each category, subtracted from unity. Uses the effect matrix from the
effects stage.
"""


def run(prior_results, config, taxonomy):
    """Compute category robustness scores for all models and categories.

    Iterates over all categories (base and compound) from the taxonomy,
    collects the perturbation effects for each, and computes a single
    robustness score per (model, category) pair.
    """
    raise NotImplementedError("Category robustness scoring not yet implemented")
