A partially-implemented R-based cardiovascular risk scoring tool is at `/app/`. It must compute 10-year risk using five published clinical models. Each model has a corresponding function in `/app/R/` and coefficient data in `/app/data/`.

**Required functions (each in its own file under `/app/R/`):**

- `ascvd_10y_accaha(race, gender, age, totchol, hdl, sbp, bp_med, smoker, diabetes)` — ACC/AHA 2013 Pooled Cohort Equations. Race/sex-stratified coefficients in `/app/data/accaha_coef.csv`. Valid ranges: age 20–79, totchol 130–320, hdl 20–100, sbp 90–200 (all inclusive). Non-white/aa race uses white coefficients. Risk floor: 1%.
- `ascvd_10y_frs(gender, age, hdl, totchol, sbp, bp_med, smoker, diabetes)` — Framingham 2008 lab-based. Gender-stratified coefficients in `/app/data/frs_coef.csv`. Valid age: 30–74. Accepts "m"/"f" abbreviations. Risk floor: 1%.
- `ascvd_10y_frs_simple(gender, age, bmi, sbp, bp_med, smoker, diabetes)` — Framingham 2008 BMI-based. Gender-stratified coefficients in `/app/data/frs_simple_coef.csv`. Valid age: 30–74. Accepts "m"/"f" abbreviations. Risk floor: 1%, cap: 30%.
- `chd_10y_mesa(race, gender, age, totchol, hdl, lipid_med, sbp, bp_med, smoker, diabetes, fh_heartattack)` — MESA 2015 CHD without CAC. Coefficients in `/app/data/mesa_coef.csv`. Race must be white/aa/chinese/hispanic. Risk floor: 1%, cap: 30%.
- `chd_10y_mesa_cac(race, gender, age, totchol, hdl, lipid_med, sbp, bp_med, smoker, diabetes, fh_heartattack, cac)` — MESA 2015 CHD with coronary artery calcium. Coefficients in `/app/data/mesa_cac_coef.csv`. Same constraints as MESA. Risk floor: 1%, cap: 30%.

**Batch processing:**

`Rscript /app/run_batch.R input.csv output.csv` must read a patient CSV with columns `patient_id, race, gender, age, totchol, hdl, sbp, bp_med, smoker, diabetes, bmi, lipid_med, fh_heartattack, cac` and write an output CSV with the original columns plus `accaha_risk, frs_risk, frs_simple_risk, mesa_risk, mesa_cac_risk`. The dispatch function in `/app/R/compute_all.R` must pass all required parameters to each calculator.

**General rules:**

- Out-of-range inputs produce NA.
- All risk scores are rounded to 2 decimal places.
- For models with `bp_med`: when treated (`bp_med=1`), systolic blood pressure contributes through the treated-SBP coefficient; when untreated (`bp_med=0`), through the untreated-SBP coefficient.
- The current implementation contains errors in multiple calculators and has incomplete functions. Fix all issues to produce numerically correct results consistent with the published coefficient tables.
