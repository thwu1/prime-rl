Mission data files in `/app/mission_data/` define the scenario parameters, target ephemeris, and ground-station tracking observations. Examine these files to determine formats, schemas, and physical parameters.

Build the following deliverables. Only `numpy` and `scipy` may be used as external Python packages. Units: km, km/s, seconds, radians.

**`/app/astro.py`** — Library exposing:

- `rv2coe(mu, r, v)` → `(p, ecc, inc, raan, argp, nu)` — `p` is semi-latus rectum. Must handle circular (ecc < 1e-8), equatorial (inc < 1e-8), and general orbits.
- `coe2rv(mu, p, ecc, inc, raan, argp, nu)` → `(r_array, v_array)` as numpy arrays. Roundtrip with `rv2coe` must agree to atol 1e-6 km / 1e-8 km/s.
- `propagate_cowell(mu, r0, v0, tof, perturbation=None, rtol=1e-12)` → `(rf, vf)`. Callback: `perturbation(t, state, mu)` → `[ax,ay,az]`, `state=[x,y,z,vx,vy,vz]`. Unperturbed case must conserve orbital energy and angular momentum to relative precision 1e-8. Must handle arbitrary perturbation profiles including tangential thrust.
- `lambert_solve(mu, r1, r2, tof, M=0, prograde=True)` → list of `(v1, v2)` tuples. M=0 yields exactly one solution; M≥1 yields up to two distinct solutions.
- `hohmann_transfer(mu, r_i, r_f)` → `(delta_v1, delta_v2, tof)`, both impulses positive.
- `j2_perturbation(t, state, mu, J2, R)` → `[ax,ay,az]`. At equator (z=0, x-aligned position), purely radial inward. At pole (r along z), purely along z. Magnitude at r=7000 km: 1e-6 to 1e-3 km/s².
- `parse_oem(filepath)` → list of dicts `{epoch_s, x, y, z, vx, vy, vz}`. `epoch_s` is seconds from the file's first data epoch.

**`/app/analyze.py`** — CLI: `python3 /app/analyze.py /app/mission_data/scenario.toml` writes `/app/results.json`:
```json
{"grid": [{"dep_s": ..., "tof_s": ..., "dv_km_s": ...}, ...],
 "optimal": {"dep_s": ..., "tof_s": ..., "dv_km_s": ...}}
```
`optimal` is the minimum-`dv_km_s` grid entry. All `dv_km_s` > 0, optimal < 15.0. Skip failed transfers.

**`/app/filtered_obs.json`** — Only quality-code "A" tracking observations. JSON array:
```json
[{"time_s": ..., "station_id": "...", "range_km": ..., "azimuth_deg": ..., "elevation_deg": ...}, ...]
```
`time_s` = seconds from the tracking file's stated reference epoch. Valid stations: GSN01, GSN02, GSN03. `range_km` > 0, `elevation_deg` in [0, 90].

**`/app/Makefile`** — GNU Make targets:
- `all`: produces `results.json`, `filtered_obs.json`, `mission.db`, `optimal_report.txt`
- `db`: loads every grid entry from `results.json` into SQLite `/app/mission.db`, table `grid_results(dep_s REAL, tof_s REAL, dv_km_s REAL)`. Row count must equal the grid array length.
- `query`: queries `mission.db` for the minimum-`dv_km_s` row, writes `/app/optimal_report.txt` as pipe-delimited text with header `dep_s|tof_s|dv_km_s` followed by one data line.
- `clean`: removes all generated files.
