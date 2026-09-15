Build a tidal turbine array wake interaction simulator and layout optimizer as a Python module at `/app/tidal_farm.py`.

The tool reads channel and turbine configuration from `/app/config.yaml`, which references turbine performance curves in `/app/turbine_data/AR2000.yaml`. Both files are present in the environment. Uniform channel flow is in the positive x-direction. The module must model velocity deficits behind turbines using a Jensen top-hat wake model with linear wake expansion and root-sum-of-squares (RSS) superposition, then optimize turbine positions to maximize total power extraction.

**Required API in `/app/tidal_farm.py`:**

`interpolate_coefficient(speed, speeds, coefficients)` — Linearly interpolate a coefficient value from tabulated speed-vs-coefficient arrays. Extrapolate using the nearest boundary value for out-of-range speeds.

`compute_wake_deficit(U_inf, Ct, D, x_downstream, y_offset, k)` — Return the absolute velocity deficit in m/s at a point `(x_downstream, y_offset)` relative to a single turbine, where `k` is the wake expansion coefficient. Return 0.0 for upstream positions or positions outside the wake envelope.

`compute_array_power(positions, config)` — Given an Nx2 numpy array of turbine (x,y) positions and a merged config dict (with keys: `channel`, `turbine`, `wake_model`, `optimization`), return `(total_power_watts, individual_powers_ndarray)`. Account for velocity deficits from upstream turbines using RSS superposition. Per-turbine power follows the standard actuator disc model with the power coefficient interpolated at the local effective velocity.

`optimize_layout(initial_positions, config)` — Return an Nx2 numpy array of optimized positions that maximize total power. Enforce box constraints keeping each turbine rotor within the farm bounds, and pairwise minimum inter-turbine distance constraints from the config. The top-hat wake model creates a discontinuous optimization landscape; a robust optimization strategy is essential.

**CLI:** `python /app/tidal_farm.py` must load the config, create an initial 4x2 regular grid of 8 turbines within the farm area (with 2-diameter margin from each farm edge), run the optimizer, and write `/app/results.json` with keys: `initial_power_watts`, `optimized_power_watts`, `improvement_percent`, `num_turbines`, `initial_positions` (list of [x,y]), `optimized_positions` (list of [x,y]).

**Success criteria:**
- Optimized power exceeds initial regular-grid power by at least 15%
- All pairwise turbine distances satisfy the configured minimum distance (1m tolerance)
- All turbine rotors remain within farm bounds (1m tolerance)
- Single-turbine power does not exceed the Betz limit
- Total array power remains below the Garrett-Cummins channel power limit
