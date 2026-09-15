Four environmental monitoring datasets from a Superfund site investigation are at `/app/data/`: `site_alpha.csv`, `site_beta.csv`, `site_gamma.csv`, and `site_delta.csv`. Each CSV has columns `value`, `censored` (0=detected, 1=non-detect), and `detection_limit`.

Produce `/app/results/analysis.json` — a JSON object keyed by dataset name (filename without `.csv`). All float values rounded to 4 decimal places. The output must conform to the field schema at `/app/output_schema.json`.

## Output fields

Every dataset entry must include: `n_total` (integer), `n_detect` (integer), `n_nondetect` (integer), `percent_nd` (float, percentage e.g. 25.0).

**Uncensored datasets** (zero non-detects) must additionally include:
- `mean`: arithmetic sample mean
- `sd`: sample standard deviation with Bessel correction (ddof=1)
- `gof`: object with goodness-of-fit results including at least `normal_pass` (boolean — Shapiro-Wilk test passes at alpha=0.01)
- `distribution`: string classification — one of `Normal`, `Gamma`, `Lognormal`, `Nonparametric` (case-insensitive in comparisons). Determined by hierarchical GOF: test normal first (Shapiro-Wilk, alpha=0.01), then gamma, then lognormal; if all fail, classify as nonparametric.
- `ucls`: object containing at minimum `t_ucl` — the Student's-t 95% UCL computed as `mean + t_crit(0.95, n-1) * standard_error`
- `recommended_method`: string naming the ProUCL-recommended UCL method. For Normal distribution, must reference "Student's-t" (contain "student" or "t"). For Gamma or Lognormal, the method must be consistent with the distribution (e.g. adjusted-CLT gamma).
- `recommended_ucl`: float value of the recommended UCL; must be greater than `mean` and positive

**Censored datasets** (non-detects present) must additionally include:
- `km_mean`, `km_sd`, `km_se`: Kaplan-Meier product-limit estimates for left-censored data. The KM algorithm must sort observations descending, place detects before censored values at ties, and accumulate probability masses as survival probability decreases.
- `km_S_final`: float — residual survival probability below the lowest observation after KM processing
- `detected_mean`: arithmetic mean of detected values only
- `dl_half_mean`: mean computed by substituting DL/2 for each non-detect, then averaging all values
- `km_inappropriate`: boolean reliability flag — `true` when any KM-based UCL falls below the `dl_half_mean` (indicating the KM estimator is unreliable due to detection limit characteristics), `false` otherwise
- `ucls`: object containing at minimum `km_t_ucl` — the KM (t) 95% UCL computed as `km_mean + t_crit(0.95, n_total-1) * km_se`
- `recommended_method`: string referencing "KM" in the method name
- `recommended_ucl`: float value of the recommended UCL; must be greater than `km_mean` and positive
- `distribution`: distribution classification of detected values (same valid set as uncensored)

## Dataset characteristics

- `site_alpha`: 20 fully detected observations, approximately symmetric — should be classified as Normal
- `site_beta`: 25 fully detected observations, heavily right-skewed — must NOT be classified as Normal (Shapiro-Wilk at alpha=0.01 must fail)
- `site_gamma`: 20 observations with 5 non-detects (25%), detection limits at 1.0 and 2.0 — KM should NOT be flagged inappropriate
- `site_delta`: 25 observations with 12 non-detects (48%), detection limits spanning 0.5 to 10.0 — the wide DL spread causes KM UCLs to fall below DL/2 mean, so `km_inappropriate` must be `true`