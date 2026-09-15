A reactor transient simulator reads configuration from `/app/data/` and produces results in `/app/results/`.

**Input files** (provided, do not modify):
- `/app/data/reactor.inp`: Reactor kinetics and thermal-hydraulic parameters in a keyword-value card format. Unit annotations appear in square brackets within comment fields. Not all values are in SI base units. The `XS_SOURCE` directive names a Fortran 90 source file in `/app/data/`.
- `/app/data/scenarios.json`: Transient scenario definitions with name, type, driving parameters, duration, and minimum output row count.
- The Fortran 90 source referenced by `XS_SOURCE` exports C-callable functions for computing reactivity feedback with nonlinear spectral correction terms. The simulator must integrate these functions — the linear coefficients in `reactor.inp` alone are insufficient for the feedback model.

**Required program**: `/app/simulate.py`, runnable via `cd /app && python3 simulate.py`

The simulator must model the reactor physics described by the input parameters, starting from critical steady-state equilibrium at nominal power. All precursor groups defined in the input must participate in the dynamics. Reactivity feedback must use the spectral correction functions exported by the Fortran source, not linear coefficients alone.

**Scenario types** in `scenarios.json` — the simulator must handle every entry. Field names and units within each scenario definition are self-documenting. For `rod_drop` scenarios, only a `measured_prompt_drop_ratio` (the ratio of neutron population immediately after to immediately before a negative step insertion) is provided; the simulator must infer the corresponding rod worth and simulate the resulting transient.

**Required output**:

`/app/results/scenario_{name}.csv` — Columns: `time_s,n_relative,T_fuel_K,T_moderator_K,rho_total,rho_external,rho_feedback`. At least `n_output_points` rows. Reactivity values in dk/k. `rho_total` must equal `rho_external + rho_feedback` at every row.

`/app/results/summary.json` — Per scenario keyed by name: `peak_power_relative`, `time_of_peak_s`, `final_power_relative`, `final_fuel_temp_K`, `final_mod_temp_K`, `final_reactivity_total`.

`/app/results/analysis.json` — For `step`-type scenarios with positive reactivity insertion: `inhour_period_s` (the asymptotic stable period). For `rod_drop` scenarios: `rod_worth_dk_k` (inferred rod worth in dk/k, negative).

**Constraints**: Temperatures in [300, 3000] K. Neutron population must remain positive. Numerical accuracy must be sufficient to match reference values within a few percent.
