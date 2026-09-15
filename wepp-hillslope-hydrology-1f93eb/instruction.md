Build `/app/wepp_pipeline.py`, a Python CLI integrating Fortran-compiled numerical routines, SQLite storage, and gnuplot visualization for WEPP surface hydrology.

**Build:** A Fortran 90 source is provided at `/app/fortran/gaml_core.f90` with C-bound subroutines `gaml_g_func`, `gaml_solve_f`, and `gaml_infil_rate`. Write `/app/Makefile` so that `make -C /app` compiles it into a position-independent shared library at `/app/libgaml.so`. The Makefile must support a `clean` target that removes generated artifacts.

**Commands:**
```
python3 /app/wepp_pipeline.py ingest <par_file>
python3 /app/wepp_pipeline.py simulate <scenario.json>
python3 /app/wepp_pipeline.py plot <scenario.json>
python3 /app/wepp_pipeline.py report <query_name>
```

**`ingest`**: Parse a CLIGEN `.PAR` station file (format: `/app/reference/par_format.md`) and store station metadata plus monthly precipitation statistics in `/app/results.db`. Sample files in `/app/stations/`.

**`simulate`**: Load `/app/libgaml.so` via Python `ctypes` and use its exported Fortran functions for the GAML infiltration computation. Run the surface hydrology model per `/app/reference/equations.md` for a storm scenario and store results in the database. Scenario files in `/app/scenarios/`. The `rainfall` array is piecewise-constant; the final entry has intensity 0.

**`plot`**: Compute the rainfall-excess timeseries for a scenario and generate a PNG hydrograph at `/app/plots/<name>.png` by invoking `gnuplot` as a subprocess. X-axis: time (min). Y-axis: rainfall excess rate (mm/hr). Title: scenario name.

**`report`**: Write a JSON array to stdout for a named query:
- `wettest-months`: `[{"station", "month", "mean_in"}, ...]` — top 3 months per station by mean precipitation, descending within each station.
- `runoff-ranking`: `[{"scenario", "net_runoff_mm", "peak_discharge_mm_hr"}, ...]` — all simulations by net_runoff_mm descending.

**Scenario JSON:**
```json
{"name": "<str>", "soil": {"Ke": <float>, "Ns": <float>, "theta_d": <float>},
 "surface": {"slope": <float>, "chezy_c": <float>, "length": <float>, "random_roughness": <float>},
 "rainfall": [{"time_min": <float>, "intensity_mm_hr": <float>}, ...]}
```

**Database schema** (`/app/results.db`):
```sql
CREATE TABLE stations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE,
  latitude REAL, longitude REAL, elevation_ft REAL, years INTEGER);
CREATE TABLE monthly_precip (station_id INTEGER REFERENCES stations(id),
  month INTEGER CHECK(month BETWEEN 1 AND 12), mean_in REAL, sd_in REAL,
  skew REAL, prob_ww REAL, prob_wd REAL, max_30min_in_hr REAL,
  PRIMARY KEY (station_id, month));
CREATE TABLE simulations (id INTEGER PRIMARY KEY AUTOINCREMENT, scenario TEXT UNIQUE,
  ponding_time_min REAL, cumulative_infiltration_mm REAL, total_rainfall_mm REAL,
  rainfall_excess_mm REAL, depression_storage_mm REAL, net_runoff_mm REAL,
  peak_discharge_mm_hr REAL, effective_duration_hr REAL);
```

**Success criteria:**
- `make -C /app` produces a loadable `/app/libgaml.so` from the provided Fortran source
- Fortran library functions are callable via ctypes and return correct numerical results
- Parsed station values match PAR data (tolerance +/-0.01); mass balance holds (+/-1%)
- No-ponding storms: `ponding_time_min = -1`, all runoff fields zero
- Hydrograph PNGs at `/app/plots/` are valid PNG images (>1 KB each)
- Reports return correctly structured, ordered JSON arrays
