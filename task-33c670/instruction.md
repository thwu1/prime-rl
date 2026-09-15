A contaminated site investigation at the Millbrook Industrial Site requires EPA-compliant 95% Upper Confidence Limits (UCLs) on the mean concentration for five contaminant-well combinations. A previous consultant produced `/app/preliminary_report.json`, but EPA Region 4 rejected the submission citing methodological deficiencies. Reference material on the applicable EPA methodology is available in `/app/reference/`.

The raw monitoring data is in `/app/site_data/`. Examine each dataset to understand its format, identify which observations are detected versus non-detected, and determine appropriate statistical treatment.

Audit the preliminary report against the methodology described in the reference materials, identify all errors, and produce a corrected analysis at `/app/results.json`.

The output JSON must be keyed by well-contaminant identifier (e.g., `MW-1_Arsenic`, `MW-2_TCE`, `MW-3_Lead`, `MW-4_Benzene`, `MW-5_Chromium`). For each entry include:

- `n`, `n_detect`, `pct_nd`
- For fully-detected data: `mean`, `sd`, and goodness-of-fit results
- For censored data: `km_mean`, `km_sd`, `ros_mean`, `ros_sd`
- `ucl_values` — a dictionary of all computed UCL estimates (at least two methods per dataset)
- `recommended_method` and `recommended_ucl`