Four CMIP6-style climate models (`CESM2`, `GFDL`, `UKESM`, `MIROC`) and a reanalysis reference dataset are stored as Zarr arrays under `/app/data/`. The catalog at `/app/data/catalog.json` maps each source to Zarr store paths for its available experiments.

Each model provides `historical` (1980–2009) and `ssp585` (2071–2100) experiments with monthly `tas` (near-surface air temperature) and `hurs` (near-surface relative humidity) on latitude–longitude grids. The reference provides historical-period data only.

These datasets originate from independent modeling centers. They follow heterogeneous conventions and contain data integrity issues that would silently corrupt downstream results if not detected and handled. No manifest of known issues is provided — discover and correct all problems through direct data inspection before computing any metrics.

Perform a thorough model evaluation: audit both variables across all models for metadata accuracy, unit consistency, coordinate conventions, and missing data; assess each model's historical temperature performance against the reference using properly area-weighted global metrics appropriate for a regular latitude–longitude grid; rank models by skill; construct a weighted multi-model ensemble; and project global-mean end-of-century warming under SSP5-8.5.

Write `/app/results.json` conforming to this schema (all floats rounded to 4 decimal places):

```json
{
  "model_diagnostics": {
    "<model>": {
      "tas_metadata_unit": "<unit string read from Zarr attrs>",
      "tas_inferred_unit": "<degC or K>",
      "needs_unit_correction": false,
      "hurs_metadata_unit": "<unit string read from Zarr attrs>",
      "hurs_is_fractional": false,
      "lon_convention": "<standard or 0_to_360>",
      "tas_has_nan": false,
      "tas_nan_month_count": 0
    }
  },
  "skill_metrics": {
    "<model>": {
      "mean_bias": 0.0,
      "rmse": 0.0,
      "pattern_correlation": 0.0
    }
  },
  "model_ranking": ["<best>", "...", "<worst>"],
  "ensemble_weights": {"<model>": 0.0},
  "equal_weight_rmse": 0.0,
  "weighted_ensemble_rmse": 0.0,
  "weighted_beats_equal": false,
  "projected_warming": {
    "<model>": 0.0,
    "weighted_ensemble": 0.0
  }
}
```

Field semantics:

- `needs_unit_correction`: `true` when the metadata-stated unit does not match the unit inferred from the data values.
- `hurs_is_fractional`: `true` when humidity is stored in the 0–1 range rather than 0–100 percent.
- `lon_convention`: `"standard"` for −180 to 180, `"0_to_360"` for 0 to 360.
- Skill metrics (`mean_bias`, `rmse`, `pattern_correlation`) are area-weighted global statistics comparing each model's corrected historical temperature against the reference. Exclude time steps with missing data from bias and RMSE computation.
- `model_ranking`: models ordered by ascending RMSE (best first).
- `ensemble_weights`: inversely proportional to RMSE, normalized to sum to 1.
- Ensemble RMSE values compare the equally-weighted and skill-weighted multi-model historical temperature means against the reference. Renormalize weights at time steps where a model has missing data.
- `projected_warming`: area-weighted global-mean temperature difference between the last 120 months of `ssp585` and the last 120 months of `historical` for each corrected model. `weighted_ensemble` is the skill-weighted average of per-model warmings.