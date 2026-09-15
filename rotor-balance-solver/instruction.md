The `/app/` directory contains a rotating machinery analysis project. C source files in `/app/src/` partially implement numerical routines with the API declared in `/app/src/balance_core.h`; the implementation in `balance_core.c` has compilation and numerical defects. The `Makefile` at `/app/Makefile` targets the shared library build but requires fixes. A legacy Python tool at `/app/legacy/` has additional defects (see its README). Reference materials are in `/app/reference/`; sample configs in `/app/configs/`.

**Deliverables:**

**`/app/libbalance.so`** — Shared library compiled from corrected and completed C source in `/app/src/`. Must export all functions declared in `balance_core.h`.

**`/app/balance_solver.py`** — Python CLI loading `/app/libbalance.so` via `ctypes`. Three subcommands:

`solve <config_path>` — Read a JSON or TOML config (detected by extension). Run the analysis per the `type` field. Write JSON to stdout.

- `"rotating"`: Input `planes` array (each: `name`, `axial_position`, `radius`, `mass`/null, `angle_deg`/null, `is_correction`). Exactly 2 correction planes. Output: `{"corrections": [{"name","mass_kg","angle_deg"},...], "residual_mr", "residual_mrx"}`. Corrections ordered by axial position; residuals < 1e-9.

- `"reciprocating"`: Input `cylinders` (`name`, `mass_kg`, `crank_radius_m`, `con_rod_length_m`, `crank_angle_deg`, `axial_position_m`), `speed_rad_s`, optional `reference_plane_m` (default 0.0), optional `correction_planes` (0 or 2 entries with `name`, `axial_position_m`, `crank_radius_m`). Output: `primary_force`/`secondary_force` with `{balanced, resultant_mr[_n], peak_N}`, `primary_moment`/`secondary_moment` with `{balanced, resultant_mrx[_n], peak_Nm}`, optional `primary_corrections`. Angles in [0, 360).

- `"flywheel"`: Input `torque_angle_data` (angle/torque pairs), `cycle_angle_rad`, `mean_speed_rpm`, optional `target_cof_speed`, `flywheel_radius_gyration_m`. Output: `mean_torque_Nm`, `energy_per_cycle_J`, `max_energy_fluctuation_J`; conditionally `required_inertia_kgm2`, `required_mass_kg`, `speed_range_rpm` (`max`/`min`).

`batch <directory> <db_path>` — Process all `.json`/`.toml` configs in the directory. Store results in SQLite at `<db_path>`, table `results`: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `config_name TEXT`, `analysis_type TEXT`, `result_json TEXT`, `mean_torque REAL`, `max_fluctuation REAL`, `residual_mr REAL`. Nullable numeric columns are NULL when the corresponding field is absent from the analysis result.

`query <db_path> <sql>` — Execute the SQL statement against the database. Write result rows as a JSON array of objects to stdout.

All tests must pass.
