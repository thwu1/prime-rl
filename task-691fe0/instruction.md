Raw synthetic CMIP6 model output from three climate models is at `/data/raw_data/{MODEL-A,MODEL-B,MODEL-C}/`. Each model directory contains numpy arrays (`tas.npy`, `hurs.npy`, `tos.npy`) with shape `(120, 36, 72)` for `(time, lat, lon)` and a `metadata.json` describing units, coordinates, and model identifiers. Units are inconsistent across models — inspect each model's metadata to determine the convention used.

Build a pipeline that produces:

**Zarr Archive** at `/app/zarr_stores/{source_id}/{variable_id}/`. Each store must contain the variable with dimensions `(time, lat, lon)` and proper coordinate arrays. Units must be standardized: temperatures in Kelvin, relative humidity in percent. Time coordinates should be monthly starting 2000-01-01. Time-axis chunk size must be 12 with spatial dimensions unchunked. Use Blosc compression with zstd codec at level 3. Consolidated metadata must be present. All data variables must carry CF-convention attributes.

**Intake-ESM Catalog** at `/app/catalog.json` (ESM Collection Spec v0.1.0 descriptor) with `/app/catalog.csv`. The catalog must support faceted search by standard CMIP6 controlled vocabulary columns and reference the Zarr stores as assets.

**Climate Diagnostics** at `/app/results.json` with these keys (all floats rounded to 4 decimal places):

- `wbt_global_mean`: Ensemble mean of each model's time-averaged, area-weighted global-mean wet-bulb temperature (°C), using the Stull (2011) regression-based approximation.
- `wbt_model_means`: Dict mapping each source_id to its time-averaged, area-weighted global-mean WBT (°C).
- `oni_positive_months`: Mean across models of the number of months where the Oceanic Niño Index exceeds +0.5 K.
- `oni_negative_months`: Same for months where ONI is below −0.5 K.
- `ensemble_wbt_spread`: Population standard deviation (ddof=0) of the three per-model mean WBT values (before rounding).
- `enso_amplitude`: Mean across models of the population standard deviation (ddof=0) of each model's ONI time series.
- `tropical_heat_stress_fraction`: Mean across models of the fraction of tropical grid-cell-months where WBT exceeds 28°C.
- `sst_global_trend`: Area-weighted global-mean SST linear trend (K/decade, OLS), averaged across models.