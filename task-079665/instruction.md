A consultant's statistical analysis of contaminated site monitoring data was rejected by a state environmental agency for non-compliance with EPA ProUCL 5.2 standards. The rejected analysis contains multiple methodological errors.

Raw monitoring data: `/app/data/site_data.csv` (columns: `sample_id`, `analyte`, `result`, `detect_flag` where 1=detected and 0=non-detect at the detection limit, `units`). Rejected analysis: `/app/original_analysis.json`.

Produce:

**`/app/results.json`** — Corrected 95% UCL analysis compliant with ProUCL 5.2. JSON object keyed by analyte. Each entry: `n` (int), `n_detect` (int), `percent_nd` (float), `distribution` (`"normal"`, `"gamma"`, `"lognormal"`, or `"nonparametric"`), `ucl_method` (string), `ucl95` (float), `mean_estimate` (float), `sd_estimate` (float).

**`/app/audit_report.json`** — Compliance audit documenting ProUCL 5.2 violations in the original analysis. JSON object keyed by analyte. Each entry: `errors` (list of strings, each a specific violation), `original_ucl95` (float), `corrected_ucl95` (float).