Three netCDF climate model output files in `/app/data/` together contain 24 months (Jan 2000 through Dec 2001) of global atmospheric data on a small latitude-longitude grid. Each file carries the variables `tas` (near-surface air temperature, K), `uas` (eastward near-surface wind, m/s), and `vas` (northward near-surface wind, m/s). Some grid cells are permanently missing (land mask).

The files were produced by different modeling groups and have formatting inconsistencies that prevent standard NCO operations from succeeding out of the box.

Produce the following outputs in `/app/output/`:

1. **`/app/output/climatology.nc`** — A 12-month climatology (one record per calendar month, each record the average of that month across both years) containing `tas`, `uas`, `vas`, and a derived variable `wind_speed = sqrt(uas² + vas²)` with appropriate metadata (`long_name`, `units`).

2. **`/app/output/global_mean_tas.nc`** — The cosine-of-latitude-weighted global spatial average of the `tas` climatology, yielding a single variable `tas` with only the `time` dimension (12 values). Missing grid cells must be excluded from the weighted average.

Available tools: NCO operators (`nco` package) and `ncdump`/`ncgen` (`netcdf-bin` package).