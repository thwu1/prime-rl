The environment at `/app/` contains:

- `/app/baseline_engine.py` — A blood gas assessment engine with calculation errors and missing functionality. Loads formula coefficients and clinical thresholds from a SQLite parameter database at runtime.
- `/app/clinical_params.sql` — SQL schema and seed data for the clinical parameter database. The engine initializes `/app/clinical_params.db` from this file on first run via `/app/init_params.py`.
- `/app/init_params.py` — Database initialization script.
- `/app/references/` — Medical reference documentation describing formulas, thresholds, and clinical interpretation rules.
- `/app/calibration/` — Validated input/output pairs (`input.json` and `expected_output.json`) for a subset of clinical scenarios.
- `/app/schema.json` — Output field specifications and classification criteria.

Build `/app/abg_assess.py` accepting `<input.json> <output.json>`. It must read a JSON array of patient blood gas and electrolyte panels and write a JSON array of comprehensive critical care assessments. Exit 0 on success. Handle 1–100 patients per file.

Errors exist in both the engine's Python logic and the parameter database seed values. Inspect and correct the database using `sqlite3` or by modifying the SQL source and reinitializing. Code-level logic errors must be fixed in the Python implementation. Not all errors are discoverable from calibration data alone — cross-reference the reference documentation to identify incorrect coefficients, thresholds, and missing edge-case handling.

**Input fields per patient**: `id`(string), `pH`, `PaCO2`(mmHg), `HCO3`(mmol/L), `Na`, `K`, `Cl`(mmol/L), `albumin`(g/L), `glucose`, `urea`(mmol/L), `measured_osmolality`(mOsm/kg), `ethanol_mg_dl`(float or null), `PaO2`(mmHg), `FiO2`(fraction), `SaO2`, `SvO2`(fractions), `PcvCO2`(mmHg), `Ca`, `Mg`, `lactate`(mmol/L), `chronicity`("acute" or "chronic").

**Required output fields**: `id`, `pH_status`, `primary_disorder`, `anion_gap`, `corrected_anion_gap`, `anion_gap_classification`, `delta_ratio`, `delta_ratio_interpretation`, `expected_paco2`, `expected_hco3`, `compensation_status`, `corrected_sodium`, `corrected_potassium`, `calculated_osmolarity`, `osmolar_gap`, `osmolar_gap_elevated`, `sid_apparent`, `sid_effective`, `strong_ion_gap`, `pf_ratio`, `ards_severity`, `o2_extraction_ratio`, `o2er_status`, `pco2_gap`, `pco2_gap_status`.

All numeric output values rounded to 2 decimal places; use unrounded intermediates for classification logic. Fields inapplicable to a patient's clinical scenario must be null.

Diagnose, correct, and extend the baseline engine to produce accurate assessments across all primary disorder types, compensation patterns, mixed disorders, and clinical edge cases not covered by the calibration set.
