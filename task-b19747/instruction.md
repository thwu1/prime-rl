Implement a Bayesian posterior inference engine in Python that estimates posterior means for three statistical models defined in `/app/models.md`. No external probabilistic programming frameworks (Stan, PyMC, NumPyro, Edward, etc.) may be used. You may use `numpy`, `scipy`, and Python standard library modules.

Data for each model is in `/app/data/`. Write output to `/app/results/<model_name>.fit` — one line per parameter: `parameter_name estimated_mean` (space-separated). Parameter names must match those listed in `/app/models.md` exactly.

The three models are:

1. **Eight Schools** — hierarchical normal model with non-centered parameterization. `tau` is positive-constrained. 18 output parameters.
2. **GP Regression** — Gaussian process with squared exponential kernel. All three parameters are positive-constrained. Requires Cholesky decomposition. 3 output parameters.
3. **SIR** — susceptible-infected-recovered epidemiological model. Requires numerical ODE integration. All four base parameters are positive-constrained. 84 output parameters (4 base + 80 transformed ODE states).

Evaluation criterion: for every parameter, `|(your_estimate - reference_mean) / reference_std| < 0.25`. Correctly handling parameter constraint transformations and their Jacobians in the log-posterior is essential for accuracy.