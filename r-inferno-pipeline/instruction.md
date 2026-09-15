A multi-file R pipeline at `/app/pipeline.R` processes clinical trial data from `/app/data/measurements.csv` and writes JSON results to `/app/output/results.json`. It sources three modules: `/app/lib/transforms.R`, `/app/lib/statistics.R`, and `/app/lib/robust.R`.

The pipeline currently fails. One sourced module does not exist and must be implemented. The remaining source files contain silent bugs that produce incorrect output across multiple result sections. Fix all issues so that `Rscript /app/pipeline.R` writes correct results.

The missing module must provide the functions called by the pipeline. Read the pipeline to determine the expected interface. Their mathematical semantics:

- **Huber M-estimator** of location per site (parameter k): iteratively reweighted mean with Huber psi-function weighting, MAD-based scale estimate (factor 1.4826), initial estimate at sample median of non-missing site measurements, convergence tolerance 1e-6, maximum 100 iterations.

- **Hodges-Lehmann estimator** per site: the median of all pairwise differences (drug_i − placebo_j) over non-missing site measurements.

The output JSON must contain these keys:

- **concentration**: `mean_concentration`, `median_concentration` (float), `n_valid` (int) — numeric concentrations only; non-numeric entries excluded.
- **quality**: `n_complete`, `n_missing` (int), `completeness_pct` (float) — non-missing vs missing measurements and percentage.
- **treatment**: `drug_mean`, `placebo_mean`, `effect_size` (float), `n_analyzed` (int) — group means over non-missing measurements, their difference, total row count.
- **weighted_effect**: `site_effects`, `site_sample_sizes` (site→value), `overall_weighted_effect` (float), `weight_used` (float, must equal 0.3) — per-site drug-minus-placebo effects, sample sizes, simple mean of site effects.
- **normalization**: `normalized_site_means` (site→float) — site non-missing measurement mean divided by site baseline mean over all rows.
- **confidence_intervals**: per-site `se`, `ci_lower`, `ci_upper` (float) — sample standard error and 95% CI (z=1.96).
- **outlier_analysis**: per-site `capped_mean` (float), `n_capped` (int) — mean after element-wise capping at (site mean + 2×sd), count exceeding cap.
- **robust_means**: per-site `huber_mean` (float), `iterations` (int) — Huber M-estimate and convergence iteration count.
- **hodges_lehmann**: site→float Hodges-Lehmann estimate.
- **summary**: `mean_normalized`, `weighted_treatment_effect`, `mean_huber_estimate`, `median_hl_effect` (float), `quality_adjusted_n` (int), `reference_baselines` (site→baseline value nearest 20.0).

All floats rounded to 6 decimal places. Numeric tolerance: 1e-4.
