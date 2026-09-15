
"""Query engine for causal inference computations on SCMs."""

import numpy as np


def compute_ate(scm, treatment, outcome, t1_val, t0_val, n_samples=100000):
    """Compute the Average Treatment Effect: E[Y|do(T=t1)] - E[Y|do(T=t0)].

    Uses Monte Carlo estimation by sampling from interventional distributions.

    Args:
        scm: SCM object with mechanisms and noise distributions configured.
        treatment: Name of the treatment variable.
        outcome: Name of the outcome variable.
        t1_val: Treatment value for the first intervention.
        t0_val: Treatment value for the second (baseline) intervention.
        n_samples: Number of Monte Carlo samples.

    Returns:
        float: Estimated ATE.
    """
    scm.n_samples = n_samples

    # E[Y | do(T = t1)]
    scm.reset_values()
    scm.sample_noise()
    scm.do_intervention(treatment, t1_val)
    scm.forward()
    y_t1 = scm.variables[outcome].value.copy()
    scm.remove_intervention(treatment)

    # E[Y | do(T = t0)] — reuse same noise for variance reduction
    scm.reset_values(reset_noise=False)
    scm.do_intervention(treatment, t0_val)
    scm.forward()
    y_t0 = scm.variables[outcome].value.copy()
    scm.remove_intervention(treatment)

    return float(np.mean(y_t1 - y_t0))


def compute_counterfactual_te(scm, treatment, outcome, t1_val, t0_val,
                               condition_vars, condition_vals,
                               n_samples=200000, tolerance=0.5):
    """Compute the Counterfactual Treatment Effect (CTF-TE):
    E[Y_{do(T=t1)} - Y_{do(T=t0)} | condition_vars = condition_vals]

    This requires Pearl's three-step counterfactual procedure:

    1. **Abduction** — Sample from the observational (pre-intervention)
       distribution and identify samples consistent with the observed
       evidence (the conditioning). The exogenous noise values for these
       samples constitute the "abducted" noise.

    2. **Action** — Modify the SCM by applying the desired hard
       intervention do(T = value).

    3. **Prediction** — Forward-compute the outcome variable using the
       modified SCM and the abducted (fixed) noise values.

    For continuous conditioning variables, exact matching is replaced by
    retaining samples within ``tolerance`` of the target value.

    Args:
        scm: SCM object with mechanisms and noise distributions configured.
        treatment: Name of the treatment variable.
        outcome: Name of the outcome variable.
        t1_val: Treatment value in the first (treatment) world.
        t0_val: Treatment value in the second (control) world.
        condition_vars: List of variable names to condition on.
        condition_vals: List of target values for those variables.
        n_samples: Number of Monte Carlo samples for estimation.
        tolerance: Window half-width for matching continuous conditions.

    Returns:
        float: Estimated E[Y_{do(T=t1)} - Y_{do(T=t0)} | conditions].

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError(
        "Implement counterfactual treatment effect via "
        "abduction-action-prediction."
    )
