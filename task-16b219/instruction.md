An intake-esm-style catalog at `/app/data/catalog/catalog.json` and `/app/data/catalog/catalog.csv` indexes synthetic CMIP6-like Zarr stores under `/app/data/zarr/`. Each store contains gridded climate variables with dimensions `(time, lat, lon)`. The catalog covers near-surface air temperature (`tas`), near-surface relative humidity (`hurs`), and sea surface temperature (`tos`) across multiple models and experiments. Variable units and metadata are stored in each Zarr array's `.zattrs` — not all models follow the same unit conventions.

Produce `/app/results.json`:

```json
{
  "wbt_reference_check": <float>,
  "wbt_extremes": {"<model>": {"<experiment>": <float>}},
  "ensemble_mean_wbt_extremes": {"<experiment>": <float>},
  "warming_amplification": {"<model>": <float>},
  "oni": {"oni_values": [<float or null>, ...]},
  "enso_events": {"el_nino_count": <int>, "la_nina_count": <int>}
}
```

- **`wbt_reference_check`**: Wet-bulb temperature (°C) for T=20°C, RH=50% via Stull's (2011) empirical approximation.
- **`wbt_extremes`**: For every model–experiment combination with both `tas` and `hurs`, the area-weighted 90th-percentile wet-bulb temperature averaged over the final 12 timesteps.
- **`ensemble_mean_wbt_extremes`**: Arithmetic mean of `wbt_extremes` across models, keyed by experiment.
- **`warming_amplification`**: Per-model ratio of WBT extreme change (ssp585 minus historical) to global area-weighted mean temperature change (ssp585 minus historical), both computed over the final 12 timesteps.
- **`oni`**: Oceanic Niño Index from `tos` for the Niño 3.4 region, per standard NOAA methodology. Use `null` where the index is undefined.
- **`enso_events`**: Distinct El Niño and La Niña episode counts from the ONI series, where an episode is 5+ consecutive months with ONI exceeding ±0.5 °C.