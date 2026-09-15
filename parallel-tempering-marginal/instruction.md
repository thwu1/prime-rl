The Bayesian model at `/app/model.stan` defines an over-parameterized binomial likelihood: two latent parameters p1 and p2 each have uniform priors on [0,1], and the observed count follows Binomial(n_trials, p1*p2). Observed data is in `/app/data.json`. CmdStan is installed at `/opt/cmdstan-2.35.0` (the environment variable `CMDSTAN` is set).

Estimate the log marginal likelihood log P(data) and posterior summary statistics for the product p1*p2.

The posterior of this model concentrates on a nonlinear manifold in the (p1, p2) space due to the product parameterization, making inference challenging.

Write results to `/app/results.json` with these fields:
- `log_marginal_likelihood` (float): estimate of log P(data), accurate within 1.5 nats
- `posterior_mean_p` (float): E[p1*p2 | data], accurate within 0.1
- `posterior_std_p` (float): std(p1*p2 | data), accurate within 0.05