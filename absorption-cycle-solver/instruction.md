The environment at `/app/` contains:

- `/app/nh3h2o_draft.py` -- a draft ammonia-water property library with errors
- `/app/data/correlations.json` -- reference coefficient tables and equation specifications
- `/app/data/benchmark.csv` -- validated benchmark values for all five correlations
- `/app/data/cycle_config.json` -- sample cycle operating conditions

The draft implementation produces results that disagree with the benchmark data. Identify and correct all errors to produce:

**`/app/nh3h2o_props.py`** exposing:

- `bubble_temperature(p_MPa, x_molar) -> float` (K)
- `dew_temperature(p_MPa, y_molar) -> float` (K)
- `vapor_composition(p_MPa, x_molar) -> float` (molar fraction)
- `liquid_enthalpy(T_K, x_molar) -> float` (kJ/kg)
- `vapor_enthalpy(T_K, y_molar) -> float` (kJ/kg)
- `bubble_pressure(T_K, x_molar) -> float` (MPa)
- `liquid_composition(p_MPa, T_K) -> float` (molar fraction)
- `molar_to_mass_fraction(x_molar) -> float`
- `mass_to_molar_fraction(w_mass) -> float`

Tolerances against benchmark: temperatures within 0.01 K, compositions within 1e-4, enthalpies within 0.5 kJ/kg. Inverse functions must achieve round-trip relative error below 1e-4. NH3 = 17.031 g/mol, H2O = 18.015 g/mol.

**`/app/cycle_solver.py`** -- CLI accepting `--config <path>`, writing JSON to stdout.

Models a single-effect NH3-H2O absorption chiller with solution heat exchanger. The 10 state points trace the solution circuit (absorber outlet, pump, SHX cold side, generator outlet, SHX hot side, expansion valve, back to absorber) and the refrigerant circuit (generator vapor outlet, condenser outlet, expansion valve, evaporator outlet).

Config keys: `T_evap_K`, `T_cond_K`, `T_gen_K`, `T_abs_K`, `shx_effectiveness`, `x_ref_molar`.

Output JSON: `P_high_MPa`, `P_low_MPa`, `x_strong_molar`, `x_weak_molar`, `f_circulation_ratio`, `COP_cooling`, `Q_evap_kJ_per_kg_ref`, `Q_gen_kJ_per_kg_ref`, `Q_cond_kJ_per_kg_ref`, `Q_abs_kJ_per_kg_ref`, `state_points` (dict `"1"` through `"10"`, each with `T_K`, `P_MPa`, `x_molar`, `h_kJ_per_kg`). All heat duties are per kg of refrigerant.

Constraints: P_low < P_high; 0 < x_weak < x_strong < 1; all four heat duties positive; 0 < COP_cooling < 1; f_circulation_ratio > 1; energy balance |Q_gen + Q_evap - Q_cond - Q_abs| < 0.01 kJ/kg; isenthalpic expansion valves; pump work negligible. Must handle `shx_effectiveness` in [0, 1] including the degenerate case of 0.
