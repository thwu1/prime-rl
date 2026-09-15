A Bayesian parameter inference pipeline for a Lotka-Volterra predator-prey ODE system is implemented at `/app/model.py` using NumPyro and JAX. The pipeline contains multiple bugs that prevent it from producing valid MCMC posterior estimates. Observed population time-series data is at `/app/data.csv`, and ground truth parameter values used to generate the data are at `/app/ground_truth.json`.

Debug and fix the pipeline so that running `python3 /app/model.py` performs NUTS MCMC inference and writes:

- `/app/results/parameters.json` — posterior summary with keys `mean`, `std`, `median`, `q5`, `q95` for each inferred parameter, including at minimum `alpha`, `beta`, `gamma`, `delta`
- `/app/results/predictions.csv` — posterior predictive means and 90% credible intervals with columns: `time`, `u_mean`, `u_lower`, `u_upper`, `v_mean`, `v_lower`, `v_upper`
- `/app/results/diagnostics.json` — MCMC convergence diagnostics (`r_hat` and `n_eff`) for at minimum the four ODE parameters (`alpha`, `beta`, `gamma`, `delta`)

The posterior estimates should recover the ground truth ODE parameter values within their 90% credible intervals, and MCMC diagnostics should indicate convergence (r_hat < 1.1, n_eff > 50 for all reported parameters). Two functions in the pipeline (`compute_predictions` and `compute_diagnostics`) are unimplemented stubs that must be completed.