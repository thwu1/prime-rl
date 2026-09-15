Synthetic CMIP6 climate model output is stored as Zarr at `/app/data/`, indexed by an intake-esm compatible catalog (`/app/catalog.json`, CSV at `/app/catalog.csv`). Four synthetic models provide monthly output for standard CMIP6 experimental protocols. Not all models include all experiments. Variable metadata and conventions may differ between models.

Perform a comprehensive climate sensitivity and heat-stress analysis of this multi-model ensemble. Write `/app/results.json` conforming to the schema below.

```json
{
  "ecs": {"MODEL": "<float, K>"},
  "feedback_parameter": {"MODEL": "<float, W m-2 K-1>"},
  "forcing_2xCO2": {"MODEL": "<float, W m-2>"},
  "tcr": {"MODEL": "<float, K>"},
  "ecs_tcr_ratio": {"MODEL": "<float>"},
  "warming_ssp585_K": {"MODEL": "<float, K>"},
  "max_wbt_C": {"MODEL": "<float, degC>"},
  "grid_cells_wbt_above_28": {"MODEL": "<int>"},
  "ecs_ensemble_mean": "<float, K>",
  "ecs_ensemble_std": "<float, K>",
  "models_outside_ipcc_likely": ["<MODEL>"],
  "ecs_ranking": ["<highest_ecs_model>", "...", "<lowest_ecs_model>"],
  "most_warming_model": "<MODEL>"
}
```

- `tcr` and `ecs_tcr_ratio`: report only for models with the relevant idealized experiment data.
- `warming_ssp585_K`: area-weighted global-mean temperature difference between ssp585 years 2091–2100 and the historical period 1995–2014, in Kelvin.
- `max_wbt_C`: maximum monthly wet-bulb temperature (Stull 2011 approximation) across all grid cells during ssp585 2091–2100.
- `grid_cells_wbt_above_28`: number of grid cells where the 2091–2100 time-mean wet-bulb temperature exceeds 28 °C.
- `models_outside_ipcc_likely`: models whose ECS falls outside the IPCC AR6 assessed "likely" range of 2.5–4.0 K.
- All spatial means must be properly area-weighted on the model grid.