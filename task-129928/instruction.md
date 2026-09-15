A prediction model for cognitive impairment from polysomnography sleep studies has been submitted to the PhysioNet Challenge 2026. Build the official evaluation pipeline that integrates heterogeneous clinical data sources, stratifies the patient cohort according to the challenge protocol, and computes the full suite of evaluation metrics with bootstrap confidence intervals and per-site sub-analyses.

## Data

- `/app/data/clinical.db` — SQLite database containing patient PSG session records, diagnosis events from multiple clinical data systems, cross-system patient linkage records, and site-specific evaluation parameters. Explore the schema to understand the available tables and their relationships.
- `/app/data/qualifying_codes.sql` — SQL dump of the official ICD-9/ICD-10 codes that define cognitive impairment for this challenge.
- `/app/data/model_output.jsonl` — JSON Lines file with the model's predictions for each patient.

## Reference Materials

The challenge's official evaluation protocol, scoring functions, data integration specifications, and documentation are at `/app/reference/`. Study all reference materials to determine the cohort stratification rules, data integration requirements, deduplication logic, the set of evaluation metrics, bootstrap CI methodology, and the expected output format.

## Output

Running `python3 /app/pipeline.py` must produce:

- `/app/output/cohort.csv` — CSV with columns `PatientID,Group` assigning every patient to the appropriate challenge-defined group.
- `/app/output/scores.json` — JSON containing overall evaluation metrics, 95% bootstrap confidence intervals (1000 iterations, seed 42, stratified by site), and per-site sub-analyses, structured as documented in `/app/reference/evaluate.py`.