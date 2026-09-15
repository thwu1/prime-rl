A geotechnical settlement analysis pipeline at `/app/` processes site investigation data, computes settlement and consolidation, and stores results in a SQLite database. The pipeline is orchestrated by a Makefile.

**Components:**

1. **Preprocessing** (`tools/preprocess.py`): Reads site configuration (INI format) and soil profiles (CSV) to produce JSON scenario files. Must correctly propagate all site-specific parameters from each config file.

2. **Settlement/consolidation engine** (`geosettle.py`): Reads a JSON scenario file path as its argument and writes JSON results to stdout. Supports rectangular, circular, and strip foundations; normally consolidated and overconsolidated settlement; and 1D finite-difference pore pressure dissipation with permeable and impermeable boundary conditions.

3. **Result storage** (`tools/store_results.py`): Stores analysis results in a SQLite database using the schema defined in `tools/schema.sql`.

4. **Makefile**: `make all` must preprocess all sites, run the engine on each, and populate `results.db` with correct data.

A predecessor settlement engine exists at `/app/geosettle_v1.py`. The Makefile references `geosettle.py`. Domain reference code from the `groundhog` geotechnical library is at `/app/reference/`. Validation scenarios with expected outputs are at `/app/validation/`.

**Site data** (in `/app/sites/`):
- `site_a/`: Two-layer overconsolidated profile, rectangular 5x8 m foundation at 100 kPa
- `site_b/`: Mixed sand/clay layers with site-specific `specific_gravity` and `unit_weight_water`
- `site_c/`: Consolidation-only analysis (no foundation)

**Expected results:**
- Site A total settlement: ~0.741 m
- Site B total settlement: ~0.086 m
- Site C midpoint excess pore pressure at t=10000 s: ~45.23 kPa

**Database schema:** `analysis_results(site_name TEXT PRIMARY KEY, total_settlement REAL, has_consolidation INTEGER, raw_json TEXT)`

**Engine standalone usage:** `python3 /app/geosettle.py <scenario.json>` must also work independently of the pipeline. Input/output JSON formats are documented in `/app/validation/*.json`.

**Success criteria:** The full automated test suite passes, verifying direct engine correctness, end-to-end `make all` pipeline execution, and correct database population.
