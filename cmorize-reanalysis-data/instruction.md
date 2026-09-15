A synthetic reanalysis dataset at `/data/raw_data/synthetic_era5_monthly_2000_2002.nc` contains five raw variables (`t2m`, `d2m`, `sp`, `tp`, `ssrd`) that must be converted to four CMIP-compliant (CMORized) output variables for climate model evaluation.

The CMOR variable specification at `/data/cmor_spec.json` defines target variable metadata, coordinate conventions, and the output filename template. Known data quality issues and ancillary correction data are documented in `/data/errata.txt`. An orography difference field is provided at `/data/ancillary/orog_diff.nc`.

Produce four CMOR-compliant NetCDF output files in `/app/output/`:

- `tas` — Near-surface air temperature, corrected for systematic bias and orographic representativeness error using the ancillary elevation data
- `huss` — Near-surface specific humidity, physically derived from dewpoint temperature and surface pressure
- `pr` — Precipitation flux, converted from monthly accumulated totals with fill value handling
- `rsds` — Surface downwelling shortwave radiation, converted from monthly accumulated energy

Each output must satisfy CF-1.7 conventions: correct variable and coordinate metadata, ascending latitude in [-90, 90], longitude in [0, 360), time as days since 1850-01-01 with mid-month values, coordinate bounds on all axes, float32 data with float64 coordinates, required global attributes, and physically correct unit transformations. Accumulated quantities must use per-month seconds as conversion denominators.