CMIP6-convention climate model output is available at `/app/data/`, described by an intake-esm catalog. Multiple models provide monthly atmospheric and oceanic variables for the historical period as Zarr stores.

Produce a multi-model analysis quantifying how global wet bulb temperature (WBT) extremes respond to ENSO variability. Use the Stull (2011) WBT approximation and the standard Oceanic Niño Index (ONI) for ENSO phase classification. For each model, report the mean of the monthly spatial 90th-percentile WBT (across all grid cells, linear interpolation) conditioned on El Niño, La Niña, and neutral months, plus the count of El Niño and La Niña months. Aggregate per-model conditional means into ensemble mean and population standard deviation (ddof=0).

Write `/app/results.json`:
```json
{
  "model_stats": {
    "<model_name>": {
      "wbt_p90_elnino_mean": <float>,
      "wbt_p90_lanina_mean": <float>,
      "wbt_p90_neutral_mean": <float>,
      "elnino_month_count": <int>,
      "lanina_month_count": <int>
    }
  },
  "ensemble": {
    "wbt_p90_elnino_mean": <float>,
    "wbt_p90_lanina_mean": <float>,
    "wbt_p90_neutral_mean": <float>,
    "wbt_p90_elnino_std": <float>,
    "wbt_p90_lanina_std": <float>,
    "wbt_p90_neutral_std": <float>
  }
}
```

All models in the catalog with valid historical experiment data must appear in `model_stats`.