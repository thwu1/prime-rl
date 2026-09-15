# MIMIC-III to MIMIC-IV Schema Differences

## Key Differences

### ICD Diagnosis Codes
- **MIMIC-III** (`diagnoses_icd`): Has column `icd9_code` containing ICD-9-CM codes only.
- **MIMIC-IV** (`diagnoses_icd`): Has columns `icd_version` (integer: 9 or 10) and `icd_code` (text).

### Patient Age
- **MIMIC-III**: Age must be computed from `patients.dob` (date of birth) and `admissions.admittime`.
  - **Important**: For patients older than 89 at admission, the date of birth has been shifted to approximately 300 years before the first admission date for de-identification purposes. These patients will appear to have ages around 300. The standard practice is to cap their age at 91.4 years (or treat as >89).
- **MIMIC-IV**: Uses `patients.anchor_age` and `patients.anchor_year` with a derived `age` table.

### Table/Column Naming
- **MIMIC-III**: Uses `icustay_id`, `row_id` present in all tables.
- **MIMIC-IV**: Uses `stay_id`, no `row_id`.

### SQL Dialect
- The reference SQL uses **Google BigQuery** syntax.
- The demo database uses **SQLite**.
- Notable differences: BigQuery `GREATEST(a, b)` → SQLite `MAX(a, b)`; BigQuery date functions differ from SQLite `julianday()` arithmetic.

## Table Schemas (MIMIC-III Demo)

### patients
| Column | Type | Description |
|--------|------|-------------|
| row_id | INTEGER | Unique row identifier |
| subject_id | INTEGER | Unique patient identifier |
| gender | TEXT | M or F |
| dob | TEXT | Date of birth (shifted for >89) |
| dod | TEXT | Date of death |
| dod_hosp | TEXT | Date of death (hospital records) |
| dod_ssn | TEXT | Date of death (social security) |
| expire_flag | INTEGER | 1 if patient died |

### admissions
| Column | Type | Description |
|--------|------|-------------|
| row_id | INTEGER | Unique row identifier |
| subject_id | INTEGER | Patient identifier |
| hadm_id | INTEGER | Hospital admission identifier |
| admittime | TEXT | Admission timestamp |
| dischtime | TEXT | Discharge timestamp |
| deathtime | TEXT | Death timestamp (NULL if survived) |
| hospital_expire_flag | INTEGER | 1 if died during admission |
| ... | ... | Other demographic/admin fields |

### diagnoses_icd
| Column | Type | Description |
|--------|------|-------------|
| row_id | INTEGER | Unique row identifier |
| subject_id | INTEGER | Patient identifier |
| hadm_id | INTEGER | Hospital admission identifier |
| seq_num | INTEGER | Diagnosis priority (1 = primary) |
| icd9_code | TEXT | ICD-9-CM diagnosis code |
