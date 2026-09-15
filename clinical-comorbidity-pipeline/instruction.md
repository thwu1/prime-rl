A SQLite database at `/app/mimic3_demo.db` contains MIMIC-III Clinical Database demo data (100 ICU patients, 129 admissions, 136 ICU stays). Tables: `patients`, `admissions`, `diagnoses_icd`, `labevents`, `d_labitems`, `icustays`, `prescriptions`.

Reference SQL files are available at `/app/reference/`:
- `charlson_mimic4.sql` — a Charlson Comorbidity Index implementation targeting MIMIC-IV on BigQuery (different schema, different SQL dialect, different ICD code format)
- `sofa_mimic4.sql` — a SOFA score implementation targeting MIMIC-IV using pre-computed derived tables (`mimiciv_derived.bg`, `mimiciv_derived.enzyme`, etc.) that do not exist in this database
- `schema_notes.md` — documents schema and dialect differences between MIMIC-III and MIMIC-IV

Produce `/app/output/results.json` containing all six keys below:

1. **`cci_per_admission`**: Object mapping each `hadm_id` (string) to its Charlson Comorbidity Index (integer, without age component). Adapt the reference SQL to work with the MIMIC-III schema and SQLite dialect.

2. **`cci_age_adjusted`**: Same structure with the age score component added. Be aware that MIMIC-III has age de-identification practices that require special handling.

3. **`sofa_lab_components`**: Object mapping each `icustay_id` (string) to an object with keys `renal`, `hepatic`, `coagulation`, `partial_sofa` (all integers). Compute from raw `labevents` using `d_labitems` to discover relevant lab item IDs. Use the worst-case lab value measured during each ICU stay window (`intime` to `outtime`) for each organ system.

4. **`suspected_sepsis`**: Object mapping each `icustay_id` (string) to a boolean. Apply a Sepsis-3-inspired screening: an ICU stay is flagged if it shows significant acute organ dysfunction (partial SOFA >= 2) AND the patient received systemic antimicrobial therapy overlapping the ICU stay.

5. **`nephrotoxic_aki_risk`**: Sorted list of `subject_id` integers for patients who had BOTH a known nephrotoxic medication AND a SOFA renal score >= 1 during the same ICU stay. Consider the standard nephrotoxic drug classes relevant to ICU pharmacovigilance. Prescription date ranges must overlap the ICU stay window. Exclude non-systemic administration routes.

6. **`risk_matrix`**: Object with keys `"0-2"`, `"3-5"`, `"6+"` (age-adjusted CCI brackets). Each maps to an object with keys `"0"`, `"1-2"`, `"3+"` (partial SOFA brackets). Values are in-hospital mortality rates (float, 4 decimal places) for ICU stays falling into each cell. Link ICU stays to admissions via `hadm_id` for CCI and `hospital_expire_flag`.