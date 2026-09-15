Posterior MCMC samples from a hierarchical Bayesian model are stored in `/app/data/`. Implement a complete prior sensitivity analysis that evaluates how the posterior distribution changes when each prior component is power-scaled (raised to a power alpha), using Pareto Smoothed Importance Sampling (PSIS) to stabilize the importance weights.

## Data

- `/app/data/samples.npz` -- Named arrays of posterior samples (one array per parameter)
- `/app/data/log_prior_components.npz` -- Log-prior density for each prior component at each sample
- `/app/data/log_likelihood.npy` -- Total log-likelihood at each sample
- `/app/data/model_spec.json` -- Contains fields: `parameters` (all parameter names), `scalar_parameters` (scalar-valued parameters only), `prior_components` (prior component names), `alpha_grid` (alpha values to evaluate), `n_samples_total` (total sample count)

## Required Output (`/app/results/`)

All four output files must be valid JSON objects (dictionaries).

**`pareto_k.json`**: Pareto shape parameter (k-hat) from PSIS for the importance weight distribution at each (prior component, alpha) combination. Keys: `"{component}_alpha_{alpha}"` (e.g. `"grand_mean_alpha_0.5"`). Values: float. Must include an entry for every combination of prior component and alpha value. Properties:
- All values must be finite
- Near-zero (< 0.35) when alpha is close to 1.0 (specifically at 0.99 and 1.01)
- Non-decreasing as alpha deviates further from 1 (k at alpha=0.5 >= k at alpha=0.99, within tolerance of 0.05)

**`ess.json`**: Effective sample size computed from the PSIS-smoothed (not raw) importance weights. Same key format as `pareto_k.json`. Values: float. Must include an entry for every combination. Properties:
- All values in range (0, `n_samples_total`]
- Non-increasing as alpha deviates from 1 (ESS at alpha=0.99 >= ESS at alpha=0.5, within tolerance of 200)
- PSIS ESS must be at least 80% of the raw (unsmoothed) importance sampling ESS for each combination

**`weighted_moments.json`**: Reweighted posterior means and variances for each parameter under each prior perturbation, using PSIS-smoothed weights. Keys: `"{param}_alpha_{alpha}_prior_{component}"`. Values: `{"mean": float, "var": float}`. Properties:
- For alpha values near 1 (0.99 and 1.01), weighted means of scalar parameters must be within 0.5 standard deviations of the unweighted posterior mean
- Weakening the `grand_mean` prior (alpha=0.5) must increase the `mu_0` posterior mean relative to the unweighted mean; strengthening it (alpha=1.5) must decrease it
- For combinations where the Pareto k-hat < 0.5, PSIS-weighted means of scalar parameters must agree with raw importance sampling means within 0.1 standard deviations of the parameter

**`sensitivity.json`**: Derivative-based sensitivity score for each parameter with respect to each prior component, defined as `Cov(param_samples, log_prior_component) / SD(param_samples)` where SD uses Bessel's correction (ddof=1). Keys: `"{param}"` mapping to `{component_name: float, ...}`. Must include all parameters and all prior components. All values must be finite. The parameter `mu_0` must be most sensitive (by absolute value) to the `grand_mean` component compared to the `noise_sd` and `group_sd` components.

## Constraints

- Do not use `arviz`, `priorsense`, `pystan`, or `cmdstanpy`
- `numpy` and `scipy` (plus standard library) are available
- Process all alpha values and all prior components from the model specification