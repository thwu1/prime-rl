`/app/data/` contains 16 years of daily observations from a groundwater monitoring well and a co-located meteorological station recording temperature (mean/min/max), relative humidity, wind speed, and incoming solar radiation, along with daily precipitation. Station metadata is in `/app/data/metadata.txt`.

Produce `/app/results.json` characterizing this aquifer's response to atmospheric forcing:

```json
{
  "et_stats": {"method": "...", "mean_mm_day": 0.0, "annual_total_mm": 0.0},
  "models": {
    "Exponential": {"evp": 0.0, "rmse": 0.0, "aic": 0.0, "n_parameters": 0},
    "Gamma": {"evp": 0.0, "rmse": 0.0, "aic": 0.0, "n_parameters": 0},
    "FourParam": {"evp": 0.0, "rmse": 0.0, "aic": 0.0, "n_parameters": 0}
  },
  "best_model": "...",
  "best_model_evp": 0.0,
  "response_time_95": 0.0,
  "step_response_gain": 0.0,
  "durbin_watson": 0.0,
  "n_observations": 0,
  "calibration_period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
  "validation": {
    "evp": 0.0,
    "rmse": 0.0,
    "period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
  },
  "residual_diagnostics": {
    "lag1_autocorrelation": 0.0,
    "seasonal_amplitude_m": 0.0
  }
}
```

- `et_stats`: Reference evapotranspiration derived from available meteorological variables; `method` names the approach
- `models`: Calibration metrics for three transfer-function groundwater models using exponential, gamma, and four-parameter impulse response functions; `evp` = explained variance percentage, `aic` = Akaike Information Criterion
- `best_model`: Lowest-AIC model name
- `response_time_95`: Days until the best model's normalized step response reaches 0.95
- `step_response_gain`: Asymptotic step response value
- `durbin_watson`: Durbin-Watson statistic on calibration residuals
- `lag1_autocorrelation`: Lag-1 autocorrelation of calibration residuals
- `seasonal_amplitude_m`: Half the range of monthly-mean calibration residuals
- `n_observations`: Total head measurements

Calibration period must be ≥ 5 years, validation ≥ 2 years, non-overlapping. EVP values in percent.