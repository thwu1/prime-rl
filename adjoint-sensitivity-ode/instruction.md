A research pipeline in `/app/` estimates the four parameters of a Lotka-Volterra predator-prey system from noisy experimental data. The pipeline is broken — running `/app/driver.py` fails or produces incorrect results due to multiple bugs spanning data loading, numerical accuracy, and optimization strategy.

## Environment

- `/app/system.py` — Correct ODE system definition with function `lotka_volterra(t, u, params)`, constant `TRUE_PARAMS = [1.5, 1.0, 3.0, 1.0]`, and constant `Y0 = [1.0, 1.0]`.
- `/app/data/observations.csv` — Noisy time-series observations in CSV format with columns `time`, `prey`, `predator` (21 rows of data).
- `/app/data/metadata.toml` — Experiment metadata including initial conditions at `initial_conditions.y0`, initial parameter guess at `initial_guess.p_init`, noise model, and variable/parameter names.
- `/app/config.toml` — Pipeline configuration with solver settings, data file paths, and output directory specification.
- `/app/driver.py` — Broken estimation driver containing multiple bugs that prevent correct operation.
- `/app/run_pipeline.sh` — Pipeline orchestration shell script.

## Requirements

1. **Diagnose the pipeline failures.** Examine and run `/app/driver.py` to identify all bugs preventing correct parameter estimates.

2. **Create `/app/estimator.py`** with the following functions (all inputs and outputs are numpy arrays):

   - `compute_gradient(params, y0, t_eval, y_data)` — Returns the gradient `dL/dp` (shape `(4,)`) of the L2 loss `L = sum_i ||u(t_i) - y_data_i||^2` with respect to ODE parameters. The gradient must be computed analytically, not via finite differences. This gradient is validated against central finite-difference approximations at two parameter sets: the initial guess parameters (`p_init` from `metadata.toml`) and the true parameters (`TRUE_PARAMS` from `system.py`). For each gradient component, relative error must be below 1%. For components where the finite-difference gradient magnitude is below 0.01, absolute error below 0.001 is accepted instead.

   - `estimate_parameters(y_data, t_eval, y0, p_init)` — Returns the estimated parameter array (shape `(4,)`). Must recover all four Lotka-Volterra parameters within 10% relative error of `TRUE_PARAMS`. The L2 loss at the estimated parameters must be less than 1% of the loss at `p_init`.

3. **Produce output files** in `/app/results/`:

   - `parameters.json` — JSON object with keys: `"recovered_params"` (array of 4 floats), `"relative_errors"` (array of 4 floats), `"converged"` (boolean). The recovered parameters must be within 10% relative error of `TRUE_PARAMS`.

   - `trajectory.csv` — CSV file with a header row. First column labeled `t` or `time`, followed by at least 2 state variable columns. Contains the trajectory simulated using the recovered parameters at the observation time points.

   - `diagnostics.json` — JSON object with keys: `"solver_method"` (string naming the ODE integration method used), `"num_function_evaluations"` (integer), `"final_loss"` (float giving the L2 loss at the estimated parameters).