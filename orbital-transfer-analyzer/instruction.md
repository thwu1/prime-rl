The directory `/app/` contains a partially-implemented orbital mechanics mission planner with defects across its Python, Makefile, and jq components.

**Components:**
- `/app/Makefile` — Build pipeline orchestration
- `/app/init.sql` — SQLite schema and mission data
- `/app/lib/orbital.py` — Computation library with bugs and unimplemented stubs
- `/app/config.toml` — Specifies missions to process
- `/app/run_missions.py` — Incomplete pipeline script
- `/app/validate.jq` — jq schema validation filter

Fix all defects, implement all stubs and missing functions, and complete the pipeline so that `cd /app && make all` exits 0, producing `/app/results.json` and `/app/report.csv`.

The `make all` target must chain four stages: database initialization via sqlite3, computation via python3, schema validation via jq, and CSV report export via sqlite3. Each stage must gate the next.

The computation stage parses `/app/config.toml` for mission IDs, queries `/app/missions.db` (joining `missions` with `bodies` for `mu`, `radius`, `j2`), computes results per mission type, and writes a JSON object keyed by mission ID to the output path specified in the config.

**Database tables:** `bodies(id, name, mu, radius, j2)`, `missions(id, body_id, type, params)` where `params` is JSON, `golden_values(mission_id, field, value, tol_abs, tol_rel)`.

**Mission types and output fields:**

- `rv2coe` — State vectors to classical orbital elements. Output: `p_km`, `ecc`, `inc_deg`, `raan_deg`, `argp_deg`, `nu_deg`
- `coe2rv` — Classical elements to state vectors. Output: `r_km` [3], `v_km_s` [3]
- `lambert` — Zero-revolution two-point boundary value problem. Output: `v0_km_s` [3], `v_km_s` [3]
- `hohmann` — Two-impulse coplanar transfer. Output: `dv_a_km_s`, `dv_b_km_s`, `dv_total_km_s`, `t_trans_s`
- `bielliptic` — Three-impulse coplanar transfer. Output: `dv_a_km_s`, `dv_b_km_s`, `dv_c_km_s`, `dv_total_km_s`, `t_trans1_s`, `t_trans2_s`
- `j2_correction` — Pericenter drift correction (body `radius` and `j2` from database). Output: `delta_t_s`, `delta_v_km_s`
- `plane_change` — Inclination change on a circular orbit. Output: `dv_km_s`
- `mission_budget` — Combined Hohmann with inclination change at departure vs. arrival. Output: `dv_depart_total_km_s`, `dv_arrive_total_km_s`, `optimal_strategy` (`"depart"` or `"arrive"`), `dv_optimal_km_s`

The report CSV must include a header row and export all rows from `golden_values`.

**Conventions:** km, km/s, seconds. Output angles in degrees; RAAN and argp in [0, 360). Delta-v non-negative. Arrays are JSON arrays of floats.

No astrodynamics libraries (poliastro, astropy, skyfield) may be used. Only NumPy and SciPy permitted.
