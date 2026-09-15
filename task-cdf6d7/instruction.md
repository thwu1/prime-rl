Non-equidistant groundwater head observations and daily meteorological forcing data are provided in `/app/`:

- `/app/head.csv` — groundwater head (meters), columns: `date`, `head`
- `/app/precipitation.csv` — daily precipitation (mm/day), columns: `date`, `precipitation`
- `/app/evaporation.csv` — daily potential evapotranspiration (mm/day), columns: `date`, `evaporation`

Meteorological records begin before head observations to allow response function warmup.

## Models

The head is modeled as: h(t) = d + sum_k theta(k) * R(t-k), where recharge R(t) = P(t) - f*E(t) with calibrated evaporation factor f, and theta is the daily-discretized impulse response (block response). Fit two models by minimizing sum of squared residuals:

**Model A (Exponential)** — theta(t) = (A/a)*exp(-t/a); parameters: A, a, f, d (4 total). The 95th-percentile response time is where the step response S(t)=A*(1-exp(-t/a)) reaches 95% of its final value.

**Model B (Gamma)** — theta(t) = A*t^(n-1)*exp(-t/a) / (a^n * Gamma(n)); parameters: A, a, n, f, d (5 total).

## Analysis

- **Model comparison**: AIC = n*ln(RSS/n) + 2k (n=observations, k=parameters). Lower AIC wins.
- **Cross-validation**: Using the AIC-selected model, calibrate on observations before 2007-01-01, validate on observations from 2007-01-01 onward. Compute calibration EVP, validation RMSE and Nash-Sutcliffe Efficiency.
- **Diagnostics**: Durbin-Watson statistic and lag-1 autocorrelation on best-model residuals.

## Output

Write `/app/results.json`:

```json
{
  "exponential_model": {
    "evp": <explained variance percentage, 0-100>,
    "rmse": <RMSE in meters>,
    "aic": <AIC value>,
    "n_parameters": 4,
    "response_time_95pct": <days>
  },
  "gamma_model": {
    "evp": <EVP>,
    "rmse": <RMSE>,
    "aic": <AIC>,
    "n_parameters": 5
  },
  "best_model": "<exponential or gamma>",
  "cross_validation": {
    "calibration_evp": <EVP on calibration period>,
    "validation_rmse": <RMSE on validation period>,
    "validation_nse": <Nash-Sutcliffe Efficiency>
  },
  "diagnostics": {
    "durbin_watson": <DW statistic>,
    "acf_lag1": <lag-1 autocorrelation>,
    "mean_residual": <mean of residuals>,
    "std_residual": <std of residuals>,
    "n_observations": <total observations>
  }
}
```