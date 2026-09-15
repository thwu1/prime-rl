Build a probabilistic forecast evaluation library at `/app/` that computes the Continuous Ranked Probability Score (CRPS) for parametric distributions and ensemble forecasts, including weighted scoring rule variants used in extreme-event verification.

## Module: `/app/scoring_rules.py`

All functions accept and return numpy arrays. You may use `scipy.special` and `scipy.stats` for standard statistical functions but must implement the CRPS computations yourself (no scoring rules libraries).

**`crps_normal(obs, mu, sigma)`** — Closed-form CRPS for the normal distribution with mean `mu` and standard deviation `sigma > 0`.

**`crps_gev(obs, shape, location=0.0, scale=1.0)`** — Closed-form CRPS for the Generalized Extreme Value distribution. The shape parameter selects the sub-family: shape=0 is Gumbel, shape>0 is Fréchet, shape<0 is Weibull. Each sub-family requires distinct mathematical treatment. Must satisfy location-shift invariance and scale homogeneity.

**`crps_gpd(obs, shape, location=0.0, scale=1.0, mass=0.0)`** — Closed-form CRPS for the Generalized Pareto Distribution. Shape parameter must be < 1. Supports a point mass `mass ∈ [0,1]` at the lower boundary. Must satisfy scale homogeneity and reduce correctly when shape=0.

**`crps_gtcnormal(obs, location, scale, lower=-inf, upper=inf, lmass=0.0, umass=0.0)`** — Closed-form CRPS for the generalized truncated and censored normal distribution. `lower`/`upper` define truncation bounds; `lmass`/`umass` are point masses at boundaries. Must reduce exactly to `crps_normal` when bounds are infinite and masses are zero. Must handle infinite bounds without producing NaN.

**`crps_mixnorm(obs, m, s, w=None)`** — Closed-form CRPS for a mixture of M normal distributions with means `m`, standard deviations `s`, and mixture weights `w`. Default equal weights when `w` is None. A single-component mixture must equal `crps_normal`.

**`crps_ensemble(obs, fct, estimator='pwm')`** — CRPS estimation for finite ensemble forecasts supporting four estimators: `nrg`, `fair`, `pwm`, `qd`. Input ensembles are not necessarily pre-sorted. The NRG and QD estimators must produce identical results, and the Fair and PWM estimators must produce identical results. Must raise `ValueError` for unknown estimators.

**`owcrps_ensemble(obs, fct, w_func)`** — Outcome-weighted CRPS for ensemble forecasts. `w_func` is a callable weight function applied to observations and forecast members. With uniform weight function w(x)=1, must equal the NRG ensemble estimator. When the observation has zero weight, owCRPS must be zero.

**`twcrps_ensemble(obs, fct, v_func)`** — Threshold-weighted CRPS for ensemble forecasts. `v_func` is a monotone chaining function used to transform the evaluation. With identity chaining v(x)=x, must equal the NRG ensemble estimator.

## Driver: `/app/evaluate.py`

Read `/app/data/scenarios.json`, compute CRPS for each scenario using the appropriate `scoring_rules` function, and write results to `/app/results.json`. Output must contain keys `"gev"`, `"gpd"`, `"gtcnormal"`, `"mixnorm"`, `"ensemble"`, each mapping to a list of objects with `"id"` and computed CRPS value(s). Ensemble scenarios must include `crps_nrg`, `crps_fair`, `crps_pwm`, `crps_qd`.