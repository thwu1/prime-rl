Build a Python analysis pipeline at `/app/analyze.py` that processes the HNSCC (Head and Neck Squamous Cell Carcinoma) radiotherapy clinical dataset at `/app/data/hnscc.csv` and writes a comprehensive analytics report to `/app/results.json`.

The dataset contains clinical records for head-and-neck cancer patients treated with radiotherapy, including TNM staging, radiation fractionation parameters, survival outcomes with censoring indicators, and L3-level body composition metrics. The CSV has encoding quirks and inconsistent column naming that must be handled.

Your analysis must compute:

**Radiobiology**: For each patient with valid dose data, compute BED (Biologically Effective Dose) and EQD2 (Equivalent Dose in 2 Gy fractions) for tumor tissue (α/β = 10 Gy) and late-responding normal tissue (α/β = 3 Gy). Report mean and std of tumor BED, mean tumor and late-tissue EQD2 across the cohort. Identify patients with dose-fractionation inconsistencies (|total_dose − dose_per_fraction × n_fractions| > 1 Gy) and patients whose overall treatment time exceeded 50 days.

**Kaplan-Meier Survival**: Implement KM estimation from scratch — do not use lifelines, statsmodels, or any dedicated survival analysis library. Compute overall survival probabilities at 12, 24, 36, and 60 months with 95% confidence intervals via Greenwood's formula. Determine median overall survival. The censoring convention is: censor = 1 means event (death), censor = 0 means censored (alive at last follow-up).

**Stage-Stratified Analysis**: Compute KM 24-month overall survival stratified by disease stage (III, IVA, IVB) with patient counts per group. Implement a two-sample log-rank (Mantel-Haenszel) test comparing Stage III versus Stage IV (IVA + IVB combined) and report the chi-square statistic and p-value (1 df).

**Body Composition**: Count pre-RT and post-RT skeletal muscle depletion using the categorical status columns. Compute all four sarcopenia transition categories (depleted→depleted, depleted→not depleted, not depleted→depleted, not depleted→not depleted). Calculate mean pre-RT SMI, mean post-RT SMI, and mean absolute SMI change for patients with valid paired measurements.

Output must conform to the schema at `/app/output_schema.json`. Run as: `python3 /app/analyze.py`