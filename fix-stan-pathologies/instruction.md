A hierarchical Bayesian AR(1) model for longitudinal panel data is provided at `/app/model.stan`. The model has multiple interacting MCMC sampling pathologies -- it produces divergent transitions, low E-BFMI, poor R-hat, and low effective sample size when fit to the simulated dataset at `/app/data.json` (10 subjects, 30 time points each). Ground truth parameters are in `/app/true_params.json`.

CmdStan is installed at `/opt/cmdstan` (environment variable `CMDSTAN` is set). The model is pre-compiled at `/app/model`. Run it with standard CmdStan sampling commands against `/app/data.json` to observe the diagnostic failures.

Diagnose all interacting pathologies in the model's parameterization and prior specification. Write a corrected Stan model to `/app/fixed_model.stan` that fits the same data and achieves:

- Zero divergent transitions across 4 chains
- E-BFMI above 0.2 on all chains
- Split R-hat below 1.05 for all parameters
- Effective sample size above 100 for all parameters
- Recovery of the AR coefficient near its true value of 0.92