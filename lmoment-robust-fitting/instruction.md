A dataset of 500 annual maximum river discharge measurements is at `/app/data/annual_maxima.csv` (one value per line, no header). The data is contaminated with approximately 3% outlier measurements. A bivariate extreme value dataset is at `/app/data/bivariate.csv` (comma-delimited, header `x1,x2`).

Produce `/app/results.json` with the following structure. All numerical values must be finite.

**`l_stats`**: Trimmed L-statistics of the univariate data — keys `l_loc`, `l_scale`, `l_skew`, `l_kurt` — computed at trim orders `(0,0)`, `(1,1)`, and `(2,2)`, nested under keys `trim_0_0`, `trim_1_1`, `trim_2_2`.

**`fits`**: Robust parameter estimates for two extreme value models fitted to the univariate data using `(1,1)`-trimmed L-moment conditions, with enough conditions that each model has at least 2 over-identifying constraints:
- `gev`: Generalized Extreme Value, 3 free parameters (shape, location, scale)
- `gumbel`: GEV with shape fixed to 0, 2 free parameters

Each entry contains: `params` (list of fitted parameters in standard order: shapes, then loc, then scale), `j_test_pvalue` (Hansen-Sargan J-test p-value from the over-identifying conditions), and `aicc` (small-sample corrected AIC computed from the profile log-likelihood evaluated at the fitted parameters).

**`best_model`**: The key (`"gev"` or `"gumbel"`) of the fit with lowest AICc.

**`return_levels`**: Estimated 100-year (`rl_100`, exceedance probability 0.01) and 1000-year (`rl_1000`, exceedance probability 0.001) return levels, nested under two keys:
- `best_model`: from the selected parametric fit
- `l_poly`: from a nonparametric quantile distribution constructed from at least 4 `(1,1)`-trimmed sample L-moments

**`l_comoment`**: Bivariate `(1,1)`-trimmed L-dependence matrices of the bivariate dataset: `l_corr` (L-correlation, 2×2 list-of-lists) and `l_coscale` (L-coscale, 2×2).

**`influence`**: Empirical influence function of the `(1,1)`-trimmed L-skewness ratio estimator evaluated at 20 equally-spaced points spanning the univariate data range. Keys: `eval_points` (list of 20 floats) and `values` (list of 20 floats).