The directory `/app/patient_data/` contains FHIR R4 Bundle JSON files, each representing a patient with demographics, laboratory results, active medications, and diagnoses. A pharmacology reference database is at `/app/pharmacology.db` (SQLite).

Perform a comprehensive medication safety audit for all patients. Assess each patient's renal function from their laboratory data, determine whether any active medications require dosage adjustment or discontinuation based on current evidence-based nephrology guidelines, and identify potential drug-drug interactions among their active medications using the reference database.

Write results to `/app/output/renal_dosing_report.json` as a JSON object with a `patients` array. Each patient entry must include:

- `patient_id`, `name`, `age` (integer), `sex`
- `serum_creatinine_mg_dl` (float, most recent value normalized to mg/dL)
- `egfr` (float, estimated glomerular filtration rate rounded to 1 decimal place)
- `ckd_stage` (KDIGO stage: G1 through G5)
- `alert_level`: `CRITICAL` if any medication must be stopped, `ADJUST` if any requires dose reduction but none must be stopped, `OK` otherwise
- `medications` array: each entry has `drug_name` (generic name, lowercase), `current_dose` (string), `action` (`STOP`/`REDUCE`/`NO_CHANGE`), `recommended_dose` (adjusted dose string if `REDUCE`, null otherwise)
- `drug_interactions` array: each entry has `drug_a`, `drug_b` (both lowercase), `severity`, and `clinical_effect` — include only interactions where both drugs are active for that patient