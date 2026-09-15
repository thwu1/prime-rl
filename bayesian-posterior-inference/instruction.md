Three Bayesian statistical models are provided at `/app/models/`. For each model, implement posterior inference in Python **without using external probabilistic programming or MCMC frameworks** (no PyMC, Stan, emcee, TensorFlow Probability, Pyro, NumPyro, or similar). Standard numerical libraries (NumPy, SciPy) are allowed.

## Models

**Eight Schools** (`/app/models/eight_schools/`): A hierarchical normal model with non-centered parameterization. Read `model.stan` for the full specification: 10 base parameters (`mu`, `tau`, `theta_tilde[1]`..`theta_tilde[8]`) and 8 deterministic transformed parameters (`theta[j] = mu + tau * theta_tilde[j]`). Observed data is in `data.json`.

**GP Regression** (`/app/models/gp_regr/`): One-dimensional Gaussian process regression with exponential quadratic kernel. Read `model.stan` for priors and likelihood structure. 3 parameters (`rho`, `alpha`, `sigma`). Observed data is in `data.json`.

**SIR Epidemic** (`/app/models/sir/`): An ODE-based compartmental epidemiological model (susceptible-infected-recovered with waterborne pathogen dynamics). Read `model.stan` for the ODE system, priors, and likelihood. 4 base parameters (`beta`, `gamma`, `xi`, `delta`) and 80 transformed parameters (`y[t,k]` for t=1..20, k=1..4) obtained by numerically integrating the ODE system. The ODE solver must be implemented from scratch (e.g., Runge-Kutta). The likelihood combines Poisson-distributed new infection counts and lognormally-distributed pathogen concentration observations. Data is in `data.json`; note that `kappa = 1000000` is defined as a constant in the model.

Each model directory contains `model.stan` (use as a reference for model definition, priors, and likelihood, but do not compile or call Stan) and `data.json` (observed data).

## Output

Write posterior mean estimates to:
- `/app/results/eight_schools.fit`
- `/app/results/gp_regr.fit`
- `/app/results/sir.fit`

Each `.fit` file must contain one line per parameter: `parameter_name estimated_mean` (space-separated), covering **all** parameters and transformed parameters defined in the corresponding Stan model.

## Accuracy

Your estimates will be evaluated against high-accuracy reference posteriors using a z-score criterion. You must achieve sufficient accuracy for all parameters across all models.

For the Eight Schools model, `theta[j]` values are nonlinear functions of correlated random variables. Their posterior means must be computed from joint posterior samples (i.e., compute `theta[j] = mu + tau * theta_tilde[j]` per sample, then average), not from marginal means.

For the SIR model, the transformed parameters `y[t,k]` are the ODE solution at each observation time. Their posterior means must be computed by solving the ODE for each posterior sample and averaging across samples.