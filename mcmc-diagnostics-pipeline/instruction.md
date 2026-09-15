The `/app/` directory contains a partially implemented MCMC convergence diagnostics pipeline. Pre-computed Markov Chain Monte Carlo trace data from two hierarchical Bayesian models is stored in `/app/data/`:

- **Model A** (`/app/data/model_a/`): Centered parameterization of a hierarchical model — known to produce convergence pathologies due to the Neal's funnel geometry. Chain files `chain_{0..3}.npy` each have shape `(2000, 10)` representing 2000 draws for 10 parameters. `log_lik.npy` has shape `(4, 2000, 8)`.
- **Model B** (`/app/data/model_b/`): Non-centered reparameterization of the same model — expected to converge well. Same data shapes.

Parameter names are in `/app/data/param_names.json`.

The diagnostics module at `/app/diagnostics.py` has bugs in existing functions and missing implementations. The pipeline at `/app/run_analysis.py` calls these diagnostics and writes results to `/app/output/diagnostics.json`.

Fix all bugs and implement all missing functions in `/app/diagnostics.py` so that the pipeline produces correct results following the modern methodology from Vehtari et al. (2021) — "Rank-Normalization, Folding, and Localization: An Improved R-hat for Assessing Convergence of MCMC" (Bayesian Analysis, 16(2):667-718). Specifically:

- `compute_rhat` must use **rank-normalized split-R-hat** (split chains, rank-normalize, then compute R-hat)
- `compute_ess` must use the **initial positive sequence estimator** for autocorrelation truncation (group consecutive pairs, stop at first negative pair sum)
- `compute_bulk_ess` must compute ESS on rank-normalized split chains
- `compute_tail_ess` must compute ESS on 5th/95th percentile indicator variables from split chains
- `compute_mcse_mean` must return `posterior_sd / sqrt(bulk_ess)`
- `compute_waic` must handle extreme log-likelihood values (some observations have log-likelihoods near -750) without producing NaN/Inf — use numerically stable log-sum-exp; use sample variance (ddof=1) for p_waic
- `generate_report` must classify parameters as "converged"/"marginal"/"failed" per the thresholds in its docstring

Run `python3 /app/run_analysis.py` to produce `/app/output/diagnostics.json`.