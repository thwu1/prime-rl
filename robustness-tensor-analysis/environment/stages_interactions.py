"""Perturbation interaction strength analysis.

For compound perturbation categories (those combining multiple base categories),
quantifies whether the combined perturbation effect is super-additive or
sub-additive relative to the individual component category effects.

Uses absolute effect magnitudes from the effect matrix to compare:
- Mean absolute effect of perturbations belonging to the compound category
- Sum of mean absolute effects across the component base categories

Positive values indicate super-additivity (combination worse than expected).
The final score for each compound category is averaged across all models.
"""


def run(prior_results, config, taxonomy):
    """Compute perturbation interaction strength for compound categories.

    For each compound category defined in the taxonomy, measures whether
    the observed combined effect is greater or less than predicted by the
    sum of individual component category effects. Returns a dict mapping
    compound category names to their interaction strength values.
    """
    raise NotImplementedError("Interaction strength analysis not yet implemented")
