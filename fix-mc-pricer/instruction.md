The project at `/app/` implements a quasi-Monte Carlo option pricing engine with a control variate framework for variance reduction. The C shared library (`libqrng.so`) provides a Sobol QRNG and inverse normal CDF, accessed from Python via `ctypes`. The engine prices European, Asian, and barrier options from `/app/contracts.json`, supporting crude Monte Carlo, antithetic variates, and control variate pricing using geometric Asian options as the control for arithmetic Asian options.

The engine is non-functional. Bugs span multiple layers:

- `/app/Makefile` — Build rules for the C shared library
- `/app/sobol.c`, `/app/norm_inv.c`, `/app/qrng.h` — C library source
- `/app/qrng_wrapper.py` — Python ctypes interface
- `/app/gbm_paths.py` — Risk-neutral GBM path simulator
- `/app/payoffs.py` — Payoff functions (barrier payoff is unimplemented)
- `/app/geo_asian.py` — Geometric Asian closed-form pricer (contains mathematical errors in the lognormal distribution parameters)
- `/app/mc_pricer.py` — MC engine with broken antithetic variates and a structurally flawed control variate integration
- `/app/main.py` — Entry point
- `/app/contracts.json` — Contract definitions

Fix all build, numerical, and mathematical errors across the C and Python layers. Derive and implement the correct closed-form geometric Asian option pricing formula (the geometric average of lognormal prices is itself lognormal — use its exact distribution parameters for the discrete monitoring case). Fix the control variate framework so it properly uses the analytical geometric Asian price as the control mean. Implement the missing barrier payoff.

After fixing the engine, evaluate variance reduction effectiveness across the contract portfolio. Produce `/app/variance_analysis.json` with a per-option-type analysis comparing crude MC, antithetic variates, and control variates (where applicable), identifying the best method and its variance reduction ratio for each option type.

Success criteria:
- The C library is a valid ELF shared object loadable via ctypes
- Sobol sequences satisfy exact stratification properties
- Inverse CDF matches known quantiles within 0.005
- GBM log-returns have correct risk-neutral mean and variance
- Geometric Asian closed-form reduces exactly to Black-Scholes when n_steps=1
- Geometric Asian price is strictly less than the corresponding European call for n_steps > 1
- Geometric Asian price decreases monotonically with n_steps (more averaging reduces price)
- Control variate method produces Asian prices consistent with crude MC
- European MC prices agree with Black-Scholes within $0.50; put-call parity holds
- Barrier prices are positive and bounded by vanilla European calls
- `/app/variance_analysis.json` identifies control variate as the best method for Asian options with variance reduction ratio > 2