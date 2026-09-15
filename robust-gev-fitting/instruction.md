Annual maximum flood peak data at `/app/data.npy` (NumPy array, 1900 float64 observations) is contaminated with spurious sensor readings. Using the `lmo` Python library, perform a robust flood frequency analysis comparing trimmed and untrimmed L-moment GEV fitting, with theoretical L-moment verification, nonparametric quantile reconstruction, and influence function robustness diagnostics.

Write `/app/results.json` with the following structure:

```json
{
  "l_stats": {
    "trim_00": [L1, L2, tau3, tau4],
    "trim_11": [L1, L2, tau3, tau4],
    "trim_22": [L1, L2, tau3, tau4]
  },
  "gev_fits": {
    "trim_00": {"shape": ..., "loc": ..., "scale": ...},
    "trim_11": {"shape": ..., "loc": ..., "scale": ...},
    "trim_22": {"shape": ..., "loc": ..., "scale": ...}
  },
  "return_levels": {
    "trim_00_100yr": ...,
    "trim_11_100yr": ...,
    "trim_22_100yr": ...,
    "trim_11_1000yr": ...
  },
  "l_moment_cov_trim_11": [[4x4 covariance matrix]],
  "theoretical_l_stats_trim_11": [L1, L2, tau3, tau4],
  "nonparametric_rl_100yr": ...,
  "influence_diagnostics": {
    "gross_error_sensitivity_tau3": ...,
    "rejection_point_tau3": ...
  }
}
```

- `shape` is `scipy.stats.genextreme`'s `c` parameter
- L-stats format: `[L-location, L-scale, L-skewness ratio tau_3, L-kurtosis ratio tau_4]`
- `trim_XY` denotes `trim=(X, Y)` in lmo
- Return levels are quantiles at exceedance probabilities (100yr = p=0.99, 1000yr = p=0.999)
- L-moment covariance is the non-parametric sample covariance of L-moment estimators for orders 1-4 with trim=(1,1)
- `theoretical_l_stats_trim_11`: theoretical L-stats `[L1, L2, tau3, tau4]` computed from the trim=(1,1) fitted GEV distribution's quantile function — these measure goodness-of-fit by comparing with the sample L-stats
- Nonparametric 100yr return level: reconstruct quantile function from first 8 TL(1,1)-moments
- Influence diagnostics: gross-error sensitivity (supremum of |IF|) and rejection point of the L-skewness ratio influence function for the trim=(1,1) fitted GEV. Note that `lmo.diagnostic.error_sensitivity` has an optimizer deficiency (COBYLA starting at x0=0 where IF=0); compute GES via `scipy.optimize.minimize_scalar` on the bounded support instead.