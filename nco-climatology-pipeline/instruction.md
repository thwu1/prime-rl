Three years of monthly climate model output (2010–2012) are in `/app/data/` as netCDF files (`climate_2010.nc`, `climate_2011.nc`, `climate_2012.nc`). These files were exported from MATLAB and contain data quality issues that prevent standard NCO operations from producing correct results.

Produce a single file `/app/output/climatology.nc` containing:

1. A 12-month climatology (one record per calendar month averaged across valid years) for variables `tas`, `uas`, and `vas`. Corrupted records must be excluded from averages, not contaminate the output.
2. A derived variable `wsp` (wind speed) computed as the vector magnitude of `uas` and `vas`.
3. A 1D variable `tas_global_mean` (dimension: `time`, 12 values) holding the cosine-latitude area-weighted global mean of `tas` for each climatological month.
4. Temperature variables (`tas` and `tas_global_mean`) converted to Kelvin.
5. CF-compliant metadata: spatial dimensions named `lat` and `lon`; `tas` with `units="K"` and `standard_name="air_temperature"`; `wsp` with `units="m s-1"` and `long_name` containing "Wind Speed"; `tas_global_mean` with `units="K"`.
6. A numeric (non-NaN) `_FillValue` for all data variables.

Investigate the input data to identify the quality issues and determine the appropriate NCO workflow. The NCO tool suite and standard netCDF utilities are available in `/usr/bin/`.