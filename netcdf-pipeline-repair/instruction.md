Three years (2018–2020) of monthly gridded climate observations are in `/app/data/` as netCDF files (`obs_2018.nc`, `obs_2019.nc`, `obs_2020.nc`). Each contains near-surface air temperature (`tas`, K) and specific humidity (`huss`, kg/kg) on a latitude/longitude grid with an ocean land-mask.

The files have multiple data quality problems typical of real-world climate archives. Inspect them, identify the issues, and build a processing pipeline using NCO (netCDF Operators) command-line tools.

Produce these outputs in `/app/output/`:

1. **`timeseries.nc`** — Clean, concatenated timeseries from all three input files.
   - Standard coordinate variable names (`lat`, `lon`).
   - Consistent, non-NaN `_FillValue` for all data variables.
   - No corrupt time records (all time values valid and monotonically increasing).

2. **`climatology.nc`** — 12-month climatology (one record per calendar month, averaged across available years).
   - Contains `tas`, `huss`, and a derived variable `vpd` (vapor pressure deficit in Pa).
   - `vpd` computed using the Tetens approximation for saturation vapor pressure and standard sea-level pressure (101325 Pa):
     - Saturation vapor pressure: `es = 611.2 * exp(17.67 * T_C / (T_C + 243.5))` where `T_C = tas - 273.15`
     - Actual vapor pressure: `ea = huss * P / (0.622 + 0.378 * huss)` where `P = 101325`
     - `vpd = es - ea`

3. **`global_means.nc`** — Latitude-weighted global means of the climatological fields.
   - Spatial dimensions (`lat`, `lon`) collapsed via area-weighted averaging using `cos(latitude)` weights.
   - Contains `tas`, `huss`, and `vpd` with only a time dimension (12 months).