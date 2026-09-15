# ProUCL 5.2 Environmental UCL Analysis Methodology

This document specifies the statistical methods for computing 95% Upper Confidence Limits
(UCLs) on the mean of environmental contaminant data, following EPA ProUCL version 5.2
methodology. The engine must handle both fully-detected (uncensored) datasets and datasets
containing non-detect (left-censored) observations.

## 1. Data Format

Each CSV file in `/app/data/` contains the following columns:

- `value`: Numeric concentration value. For detected observations, this is the measured
  concentration. For non-detects, this equals the detection limit.
- `censored`: Integer flag. `0` = detected (observed), `1` = non-detect (left-censored
  below the detection limit).
- `detection_limit`: The detection limit value for censored observations. Empty string
  for detected observations.

## 2. Statistics for Uncensored Datasets

For datasets with zero non-detects, compute:

- **Mean**: Arithmetic sample mean
- **SD**: Sample standard deviation with Bessel's correction (ddof=1)
- **SE**: Standard error = SD / sqrt(n)
- **Skewness**: Adjusted Fisher-Pearson coefficient:
  `G1 = [n / ((n-1)(n-2))] * sum(((xi - mean) / SD)^3)`

## 3. Kaplan-Meier Estimator for Left-Censored Data

For datasets with non-detects, use the Kaplan-Meier (KM) product-limit estimator
adapted for left-censored data. This is the core algorithm:

### Algorithm

1. Create observation list: for each row, store `(value, is_detected)`. For censored
   rows, use the detection_limit as the value.
2. Sort observations by value in **descending** order. For tied values, place detected
   observations **before** censored observations.
3. Initialize: `n_risk = n_total`, `S = 1.0` (survival probability)
4. Process each unique value `v` from largest to smallest:
   - `d` = count of detected observations at value `v`
   - `c` = count of censored observations at value `v`
   - `S_new = S * (1 - d / n_risk)` (update survival; if d=0, S is unchanged)
   - `mass = S - S_new` (probability mass assigned to this detected value)
   - `n_risk = n_risk - d - c` (remove both detected and censored from risk set)
   - `S = S_new`
5. After processing all values, `S_final` = remaining survival probability (probability
   mass below the lowest detection limit, unaccounted for).

### KM Statistics

- `KM_mean = sum(v * mass)` over all unique detected values (where mass > 0)
- `KM_var = sum(v^2 * mass) - KM_mean^2`
- `KM_SD = sqrt(KM_var)`
- `KM_SE = KM_SD / sqrt(n_total)`

### KM Inappropriate Flag

When detection limits span an order of magnitude or more, the KM estimator may produce
unreliable results. Compute the **DL/2 substitution mean**: replace each non-detect with
half its detection limit, then compute the arithmetic mean of all values.

Set `km_inappropriate = True` if **any** KM-based UCL value is less than the DL/2
substitution mean.

## 4. Goodness-of-Fit Testing

Apply tests hierarchically in this order with the specified significance levels.
For censored datasets, apply GOF tests to the **detected values only**.

### 4.1 Normality Test

- Test: **Shapiro-Wilk W** test
- Significance level: **alpha = 0.01**
- Pass condition: p-value > 0.01
- Requires n >= 3

### 4.2 Gamma Distribution Test

- Test: **Kolmogorov-Smirnov** test against gamma distribution with parameters
  estimated by Maximum Likelihood (MLE), with location parameter fixed at zero.
- Significance level: **alpha = 0.05**
- Pass condition: p-value > 0.05
- Requires all values > 0 and n >= 3

### 4.3 Lognormality Test

- Test: **Shapiro-Wilk W** test on natural-log-transformed data
- Significance level: **alpha = 0.10**
- Pass condition: p-value > 0.10
- Requires all values > 0 and n >= 3

### Hierarchical Classification

Apply tests in order. The **first** distribution to pass determines the classification:

1. If normality passes: classify as `"Normal"`
2. Else if gamma passes: classify as `"Gamma"`
3. Else if lognormality passes: classify as `"Lognormal"`
4. Else: classify as `"Nonparametric"`

## 5. UCL Computation Methods

### 5.1 Uncensored Data UCLs

Compute all of the following:

**Student's t UCL:**
`t_ucl = mean + t(0.95, n-1) * SE`
where `t(0.95, n-1)` is the 95th percentile of the Student's t distribution.

**Adjusted-CLT Gamma UCL:**
`gamma_adj_ucl = mean + z(0.95) * SE * (1 + skewness / (3 * sqrt(n)))`
where `z(0.95) = 1.6449...` is the 95th percentile of the standard normal.

**Chebyshev UCL** (computed for reference; never recommended in ProUCL 5.2):
`chebyshev_ucl = mean + sqrt((1/alpha - 1) / n) * SD`
where alpha = 0.05, giving `sqrt(19/n) * SD`.

### 5.2 Censored Data UCLs (KM-based)

Compute all of the following using KM statistics:

**KM (t) UCL:**
`km_t_ucl = KM_mean + t(0.95, n_total - 1) * KM_SE`

**KM Chebyshev UCL** (computed for reference; not recommended):
`km_chebyshev_ucl = KM_mean + sqrt(19 / n_total) * KM_SD`

## 6. Decision Logic for UCL Recommendation

### 6.1 Uncensored Datasets

Based on the distribution classification:

- **Normal**: Recommend `"Student's-t UCL"` with value `t_ucl`
- **Gamma**: Recommend `"Adjusted-CLT Gamma UCL"` with value `gamma_adj_ucl`
- **Lognormal**: If n >= 20, recommend `"Adjusted-CLT Gamma UCL"` with value
  `gamma_adj_ucl`. If n < 20, recommend `"Student's-t UCL"` with value `t_ucl`.
- **Nonparametric**: Recommend `"Student's-t UCL"` with value `t_ucl`

### 6.2 Censored Datasets

Default recommendation: `"KM (t) UCL"` with value `km_t_ucl`.

## 7. Output Format

Write results to `/app/results/analysis.json` as a JSON object keyed by dataset name
(filename without `.csv` extension). Each entry must contain:

### For uncensored datasets:
```json
{
  "n_total": <int>,
  "n_detect": <int>,
  "n_nondetect": <int>,
  "percent_nd": <float>,
  "mean": <float>,
  "sd": <float>,
  "se": <float>,
  "skewness": <float>,
  "gof": {
    "normal_pvalue": <float>,
    "normal_pass": <bool>,
    "gamma_pvalue": <float>,
    "gamma_pass": <bool>,
    "lognormal_pvalue": <float>,
    "lognormal_pass": <bool>
  },
  "distribution": "<string>",
  "ucls": {
    "t_ucl": <float>,
    "gamma_adj_ucl": <float>,
    "chebyshev_ucl": <float>
  },
  "recommended_method": "<string>",
  "recommended_ucl": <float>
}
```

### For censored datasets:
```json
{
  "n_total": <int>,
  "n_detect": <int>,
  "n_nondetect": <int>,
  "percent_nd": <float>,
  "km_mean": <float>,
  "km_sd": <float>,
  "km_se": <float>,
  "km_S_final": <float>,
  "detected_mean": <float>,
  "dl_half_mean": <float>,
  "km_inappropriate": <bool>,
  "gof_on_detects": {
    "normal_pvalue": <float>,
    "normal_pass": <bool>,
    "gamma_pvalue": <float>,
    "gamma_pass": <bool>,
    "lognormal_pvalue": <float>,
    "lognormal_pass": <bool>
  },
  "distribution": "<string>",
  "ucls": {
    "km_t_ucl": <float>,
    "km_chebyshev_ucl": <float>
  },
  "recommended_method": "<string>",
  "recommended_ucl": <float>
}
```

Round all floating-point values to 4 decimal places in the output.
