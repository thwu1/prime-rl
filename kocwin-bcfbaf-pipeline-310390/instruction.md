EPA EPI Suite's KOCWIN v2.01 module estimates soil organic carbon-water partition coefficients (Koc) via two regression methods — one based on molecular connectivity index (MCI), the other on log Kow. Each method uses chemical-class-dependent equation selection and per-occurrence fragment corrections for polar functional groups. BCFBAF v3.02 estimates bioconcentration factors (BCF) from log Kow with equation branching for ionic compounds.

Build `/app/episuite_pipeline.py` that reads `/app/compounds.json` (29 chemicals) and produces:

**`/app/results.json`** — JSON array of 30 objects: 29 per-chemical records plus one summary.

Per-chemical fields: `cas`, `koc_mci_log`, `koc_mci`, `koc_kow_log`, `koc_kow`, `bcf_log`, `bcf`, `koc_mci_residual`, `koc_kow_residual`, `better_method`.
- Log Koc clamped to minimum 0.0 after corrections
- Linear Koc: 10^(log value), rounded to 1 decimal if <1000, nearest integer otherwise
- BCF: 10^(bcf_log), rounded to 2 decimal places
- Residuals: log estimate minus `logKoc_experimental`; null when no experimental data
- `better_method`: `"mci"` or `"kow"` (smaller |residual|); null when no data

Summary (`cas` = `"SUMMARY"`): `mci_rmse`, `kow_rmse` (RMSE of respective residuals; each in 0.05-1.5), `mci_wins`, `kow_wins` (method comparison counts; sum = count with experimental data), `mean_bcf_log` (mean across 29 chemicals).

**`/app/results.db`** — SQLite database with three tables:
- `equations(method TEXT, equation_type TEXT, coefficient_a REAL, coefficient_b REAL)` — 4 regression equations: MCI-Koc, Kow-Koc nonpolar, Kow-Koc polar/acid, BCF standard
- `fragment_corrections(method TEXT, fragment_name TEXT, correction_value REAL)` — correction factors for both MCI and Kow methods, where `method` is `'mci'` or `'kow'` and `fragment_name` matches the identifiers used in the `functional_groups` field of the input
- `compound_results(cas TEXT, koc_mci_log REAL, koc_mci REAL, koc_kow_log REAL, koc_kow REAL, bcf_log REAL, bcf REAL, koc_mci_residual REAL, koc_kow_residual REAL, better_method TEXT)` — per-chemical results matching JSON output

**Input** (`/app/compounds.json`): each object has `cas`, `name`, `smiles`, `logKow_experimental`, `mci`, `is_organic_acid`, `is_ionic`, `functional_groups` (repeats = per-occurrence corrections), `logKoc_experimental` (float or null).

Equation parameters, fragment corrections, and branching rules are not provided in the environment. The EPI Suite REST API is accessible at `https://episuite.dev/api/`.

Acceptance: log values +/-0.015; linear values 5% relative; all 30 JSON records present; SQLite database with correct schema, 4 equation rows, at least 13 corrections per method, and compound results consistent with JSON output.
