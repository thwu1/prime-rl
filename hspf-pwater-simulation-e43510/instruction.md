Build `/app/pwater.py` — a standalone HSPF-compatible PWATER (pervious-land water budget) simulator that reads domain-specific configuration, runs a hydrological simulation, and writes results to a structured HDF5 file.

**Provided files:**

- `/app/watershed.uci` — HSPF User Control Input file for a single PERLND segment. Contains simulation timing in the GLOBAL and OPN SEQUENCE blocks, PWATER flags (PWAT-PARM1), calibration parameters (PWAT-PARM2 through PWAT-PARM4), monthly interception capacity (MON-INTERCEP), and initial storage states (PWAT-STATE1). Uses standard HSPF fixed-width text format with section delimiters, comment lines (`***`), and template lines (`<` or `#` prefixed). Non-PWATER sections must be ignored.
- `/app/forcing.csv` — hourly time series with columns PREC (precipitation) and PETINP (potential evapotranspiration), in inches.
- `/app/pwater_ref.py` — reference Python implementation of the PWATER algorithm from the HSPsquared project. Depends on numpy, numba, and hsp2 libraries that are **not installed**. Read-only algorithmic reference.

**Required output:**

`/app/output.h5` — an HDF5 file with this exact structure:

- Group `/PERLND/P101/PWATER/` containing float64 datasets (each shape `(N,)` where N = number of forcing timesteps):
  - `SURO` — surface runoff (inches/interval)
  - `IFWO` — interflow outflow
  - `AGWO` — active groundwater outflow
  - `PERO` — total pervious outflow (= SURO + IFWO + AGWO)
- Group `/PERLND/P101/STATE/` containing float64 datasets (each shape `(N,)`):
  - `UZS` — upper zone storage at end of each step
  - `LZS` — lower zone storage at end of each step
  - `AGWS` — active groundwater storage at end of each step
- Group `/SUMMARY/` with float64 attributes:
  - `total_precip`, `total_outflow`, `total_et`, `water_balance_error`, and integer attribute `simulation_hours`
  - `water_balance_error` is the absolute mass-balance residual: |Σprecip − Σoutflow − Σ(actual ET) − Σ(deep losses) − Δstorage|
- Root-level string attributes: `model` = `"HSP2-PWATER"`, `segment_id` = `"P101"`
- All datasets must use gzip compression (compression level ≥ 1).

**Run command:** `python3 /app/pwater.py`

**Acceptance criteria:**

- Valid HDF5 with all specified groups, datasets, attributes, and gzip compression.
- Cumulative sums of SURO, IFWO, AGWO, and PERO each within 0.01 inches of reference.
- Per-step accuracy < 0.001 at timesteps 0, 180, and first rain event.
- All flow and state values ≥ 0. PERO[i] ≡ SURO[i]+IFWO[i]+AGWO[i] within 1e-10 at every step.
- Water balance error < 0.05 inches.
- During initial dry period (PREC = 0), SURO < 1e-8. SURO must exceed 1e-6 somewhere during rainfall.
