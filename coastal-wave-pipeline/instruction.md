The `/app/` directory contains scenario JSON files, CEM reference material, Owen coefficient data, and raw bathymetric surveys. Build a coastal wave transformation system that produces correct results for all pre-populated scenarios.

**Required deliverables:**

`/app/Makefile` with targets: `all`, `lib`, `preprocess`, `analyze`, `clean`.

`/app/src/dispersion.c` compiled to `/app/lib/libdispersion.so`, exporting:
```c
int solve_dispersion(double T, double d, double *out);
```
`out` receives `[L, C, Cg, k, n]`. Returns 0 on success.

`/app/preprocess.awk` — processes `/app/raw_surveys/*.survey` into `/app/profiles/*.json`. Output schema: `[{"station":"...","depth_m":...}]`. Skips comments (`#`), blank lines, and incomplete records. Converts ft elevations to m depths. Excludes non-submerged entries.

`/app/coastal_pipeline.py` — CLI taking a scenario JSON path as its sole argument. Calls the C shared library at `/app/lib/libdispersion.so` for all dispersion calculations. Writes result JSON to stdout. Persists every result in `/app/results.db`.

**Output schemas** (keyed by `"mode"` in each scenario JSON):

| Mode | Output fields |
|------|--------------|
| `dispersion` | `results[]`: `d, L, C, Cg, k, n` |
| `transect` | `results[]`: `d, H, theta, Ks, Kr` |
| `breaking` | `Hb, db, gamma_b` |
| `setup` | `eta_b, eta_s, eta_max, shoreline_displacement_m` |
| `runup` | `Rmax, R2pct, R_1_10, R_1_3, R_mean` |
| `overtopping` | `owen.q, vdm.q` |
| `full` | `breaking, setup, runup, overtopping, total_water_level` |

**SQLite schema** — table `scenario_results` in `/app/results.db`:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `scenario_name` TEXT UNIQUE
- `mode` TEXT
- `input_json` TEXT
- `output_json` TEXT
- `timestamp` TEXT DEFAULT (datetime('now'))

**Tolerances:** g = 9.81 m/s^2. Angles in degrees. Numerical results must match CEM worked-example values within 5% relative tolerance (when |expected| > 0.1) or 0.05 m absolute.
