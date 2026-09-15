# EPA ProUCL 5.2 - Statistical Methodology Reference

## Purpose

ProUCL 5.2 is EPA's recommended statistical software for computing Upper Confidence
Limits (UCLs) on the population mean for environmental site characterization. UCLs
serve as Exposure Point Concentrations (EPCs) in human health and ecological risk
assessments under CERCLA and RCRA.

## Distribution Testing

Before selecting a UCL method, ProUCL evaluates data against three parametric
distribution families using goodness-of-fit (GOF) testing:

- **Normal**: Shapiro-Wilk test at alpha = 0.05
- **Gamma**: Anderson-Darling or Kolmogorov-Smirnov test
- **Lognormal**: Shapiro-Wilk test applied to log-transformed values

Distribution identification is the primary driver of UCL method selection.

## Available UCL Methods

ProUCL 5.2 computes multiple UCL estimates simultaneously for comparison. The
software then recommends the most appropriate method based on distribution fit,
sample size, and data characteristics.

Available methods for fully-detected datasets include:
- Student's t UCL — standard parametric, assumes approximate normality
- Modified-t UCL — adjustment for moderate skewness
- Chebyshev (MVUE) UCL — distribution-free, based on Chebyshev inequality
- Bootstrap percentile UCL
- BCA (bias-corrected and accelerated) bootstrap UCL
- Hall's bootstrap-t UCL — studentized bootstrap
- H-UCL (Land's method) — designed specifically for lognormal data
- Gamma-based UCLs — adjusted gamma, approximate gamma

## Key Changes in Version 5.2 (from 5.1)

ProUCL 5.2 introduced significant changes to UCL recommendation logic based on
extensive simulation studies (see Technical Guide Appendix D):

1. **Chebyshev UCL is NEVER recommended** — simulation studies demonstrated that
   the Chebyshev UCL produces gross overestimates of the true mean, leading to
   unacceptably high Type II error rates (concluding contamination exists when it
   does not). While it achieves high coverage, accuracy is unacceptable.

2. **H-UCL restrictions** — The Land's H-UCL is only recommended when:
   - Sample size n >= 70, OR
   - Data passes lognormality GOF AND skewness is moderate
   For smaller samples or highly skewed lognormal data, H-UCL can produce
   extreme overestimates.

3. **Bootstrap method restrictions** — Bootstrap and resampling-based methods
   (BCA, Hall's, percentile) are NOT recommended for sample sizes n < 10.
   Small samples lack sufficient information for reliable resampling.

4. **Reproducible bootstrap** — Fixed random seed ensures deterministic results.

5. **Balanced error control** — The v5.2 philosophy balances Type I error
   (false negative: site is contaminated but declared clean) against Type II
   error (false positive: site is clean but declared contaminated).

## Non-detect (Left-censored) Data

Environmental monitoring datasets frequently contain non-detect (ND) observations
where the analyte concentration falls below the analytical method's detection
limit (DL). The true concentration is known only to be somewhere between zero
and the DL.

### Methods NOT Recommended by EPA

Simple substitution methods — replacing non-detects with DL/2, DL, DL/sqrt(2),
or zero — are **not recommended** by EPA for UCL computation. These methods:
- Introduce systematic bias in mean and variance estimates
- Do not properly account for the uncertainty in censored observations
- Can underestimate or overestimate the true mean depending on the data
- Are not statistically defensible under current EPA guidance

### Recommended Censored-data Methods

ProUCL 5.2 recommends:
- **Kaplan-Meier (KM)** product-limit estimator, adapted for left-censored data
- **Regression on Order Statistics (ROS)** — fits a parametric model to detected
  values and imputes non-detects based on their expected quantile positions
- **Maximum Likelihood Estimation (MLE)** under distributional assumptions

UCLs for censored data are computed using the KM or ROS-based mean and standard
deviation estimates, then applying analogous UCL formulas (e.g., KM-t, KM-BCA).

### High Censoring Warning

When non-detect percentage exceeds 50%, ProUCL flags the results as potentially
unreliable. The KM estimator may produce unstable estimates with very high
censoring rates, and results should be interpreted with caution.

## Small Sample Considerations

For datasets with n < 10, ProUCL restricts recommendations to simple parametric
methods (typically t-based). Bootstrap, gamma, and other methods requiring
larger samples are not recommended regardless of distributional fit.
