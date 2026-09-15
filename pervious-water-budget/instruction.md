A HSPF UCI file at `/app/watershed.uci` defines two pervious land segments (P001, P002) for the PWATER module. Hourly inputs at `/app/input_timeseries.csv` (columns: `PREC`, `PETINP`; 8760 rows; inches/interval). Area weights at `/app/area_weights.json`.

Produce all of the following in `/app/`:

**`parsed_config.json`** — Parsed UCI configuration. Schema: `{"P001": {"parameters": {CSNOFG, RTOPFG, UZFG, VCSFG, FOREST, LZSN, INFILT, LSUR, SLSUR, KVARY, AGWRC, INFEXP, INFILD, DEEPFR, BASETP, AGWETP, CEPSC, UZSN, NSUR, INTFW, IRC, LZETP}, "states": {CEPS, SURS, UZS, IFWS, LZS, AGWS, GWVS}, "monthly_cepsc": [12 values]}, "P002": ...}`. Include `monthly_cepsc` (12 floats) only when VCSFG=1; omit or set null when VCSFG=0. All parameter and state values must match the UCI file exactly.

**`output_P001.csv`**, **`output_P002.csv`** — Hourly PWATER simulation results: columns `SURO`, `IFWO`, `AGWO`. 8760 rows, inches/interval.

**`output.csv`** — Area-weighted aggregate of per-segment outputs.

**`results.h5`** — HDF5 archive:
- `/metadata` group with attributes: `start_date` (string), `end_date` (string), `units` (int), `num_segments` (int, must equal 2)
- `/segments/<id>/parameters/` — one scalar float64 dataset per parsed parameter
- `/segments/<id>/states/` — one scalar float64 dataset per initial state variable
- `/segments/<id>/hourly/{SURO,IFWO,AGWO}` — float64 arrays, shape (8760,)
- `/aggregate/{SURO,IFWO,AGWO}` — area-weighted float64 arrays, shape (8760,)
HDF5 hourly data must be numerically identical to the CSV outputs.

**`watershed.db`** — SQLite database with tables:
- `segments(segment_id TEXT PRIMARY KEY, forest REAL, lzsn REAL, infilt REAL, agwrc REAL, kvary REAL)`
- `hourly_output(segment_id TEXT, hour INTEGER, suro REAL, ifwo REAL, agwo REAL)` — 17520 rows total (8760 per segment)
- `water_balance(segment_id TEXT PRIMARY KEY, total_precip REAL, total_et REAL, total_suro REAL, total_ifwo REAL, total_agwo REAL, total_deep REAL, balance_error REAL)`
`balance_error` is the absolute water budget closure error (must be < 0.5). Water balance totals must be consistent with the CSV sums. `total_precip` must be positive.

**Acceptance criteria:**
- Parsed parameters and states match UCI values. Monthly CEPSC present for P001 (VCSFG=1), absent/null for P002 (VCSFG=0).
- CSV values non-negative, below 10.0. No all-zero columns.
- Per-segment column sums accurate within 0.01. Spot-checked timestep values within 5% relative or 1e-5 absolute.
- SURO responds to precipitation events (PREC > 0.05). AGWO recedes during dry periods.
- IFWO totals within 50–200% of correct values.
- Aggregate equals area-weighted sum of segments within 1e-8.
- HDF5 hierarchy, attribute types, dataset shapes, and parameter/state values match specification. Hourly data matches CSV exactly.
- SQLite schemas, row counts, data values, and water balance closure match specification.

**Notes:**
UCI uses fixed-width columns; `***` and `<` lines are comments. GLOBAL section contains simulation period and unit system. PWATER simulates hourly water movement through coupled storages with state carryover between timesteps. Internet available.
