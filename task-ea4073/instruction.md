A synthetic 10-year daily maximum temperature dataset is at `/app/data/tasmax_daily.nc` (variable `tasmax`, units Kelvin, Gaussian N16 grid, years 2001-2010, 3652 daily timesteps).

Write a shell script `/app/pipeline.sh` that uses CDO to produce the following files in `/app/results/`:

- **`tasmax_regrid.nc`** — Input data conservatively remapped to a regular 10-degree global grid (36 longitudes x 18 latitudes).

- **`pctl90.nc`** — Multi-year daily running 90th percentile of the regridded tasmax, computed from the reference period 2001-2005 with a 5-day running window. The percentile operator requires companion running-minimum and running-maximum files computed from the same data and window size as auxiliary inputs.

- **`wsdi.nc`** — ECA Warm Spell Duration Index (warm-spell days w.r.t. 90th percentile) for evaluation years 2006-2010, using the percentile field from the previous step as the exceedance threshold. Output must contain one annual value per evaluation year (5 timesteps total).

- **`ymon_clim.nc`** — Multi-year monthly mean climatology of regridded tasmax from the reference period 2001-2005 (12 timesteps, one per calendar month).

- **`monthly_anomalies.nc`** — Monthly anomalies for the full period 2001-2010, obtained by subtracting the per-month climatology from corresponding monthly means of the regridded data (120 timesteps).

- **`fldmean_anomalies.nc`** — Area-weighted global field mean of the monthly anomalies (120 timesteps, single grid point).

Run the pipeline after creating it.