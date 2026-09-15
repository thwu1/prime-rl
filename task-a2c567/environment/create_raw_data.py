"""Generate a raw, non-CMOR-compliant NetCDF file for the CMORization task.

Uses a 360-day calendar and non-standard conventions to create a realistic
raw observational dataset requiring expert-level CMORization."""
import sys

import netCDF4 as nc
import numpy as np

np.random.seed(42)

output_dir = '/app/raw_data'
import os
os.makedirs(output_dir, exist_ok=True)
filepath = os.path.join(output_dir, 'station_obs_monthly_2000-2002.nc')

nlon = 144
nlat = 73
ntime = 36  # 3 years x 12 months

# Coordinates (deliberately non-CMOR-compliant)
lon = np.arange(-180, 180, 2.5, dtype=np.float32)   # Wrong: should be 0-360
lat = np.linspace(-90, 90, nlat, dtype=np.float32)   # Wrong dtype: should be float64

# Time: 360-day calendar (30 days per month, 360 days per year)
# Mid-month values: day 14.5 of each 30-day month
time_vals = []
for t in range(ntime):
    days = t * 30 + 14.5  # mid-month in 360-day calendar
    time_vals.append(days)
time_vals = np.array(time_vals, dtype=np.float64)

# Create file
ds = nc.Dataset(filepath, 'w', format='NETCDF4')

# Dimensions --- time is NOT unlimited (deliberate issue)
ds.createDimension('time', ntime)
ds.createDimension('latitude', nlat)
ds.createDimension('longitude', nlon)

# Time coordinate --- 360_day calendar (non-standard, requires conversion)
time_var = ds.createVariable('time', 'f8', ('time',))
time_var[:] = time_vals
time_var.units = 'days since 2000-01-01 00:00:00'
time_var.calendar = '360_day'
time_var.long_name = 'time'
# NO bounds --- deliberate omission

# Latitude --- wrong units, missing standard_name
lat_var = ds.createVariable('latitude', 'f4', ('latitude',))
lat_var[:] = lat
lat_var.units = 'degrees'           # Wrong: should be 'degrees_north'
lat_var.long_name = 'latitude'
# NO standard_name --- deliberate omission

# Longitude --- wrong units, wrong range, missing standard_name
lon_var = ds.createVariable('longitude', 'f4', ('longitude',))
lon_var[:] = lon
lon_var.units = 'degrees'           # Wrong: should be 'degrees_east'
lon_var.long_name = 'longitude'
# NO standard_name --- deliberate omission

# Meshgrid for data generation
lat_grid, lon_grid = np.meshgrid(lat, lon, indexing='ij')

# --- Variable 1: t2m (temperature in Fahrenheit as float32) ---
t2m_data = np.zeros((ntime, nlat, nlon), dtype=np.float32)
for t in range(ntime):
    month = (t % 12) + 1
    base_C = 25.0 - 0.5 * np.abs(lat_grid)
    seasonal_C = 10.0 * np.sin(2 * np.pi * (month - 7) / 12.0) * np.sign(lat_grid)
    noise_C = 3.0 * np.random.randn(nlat, nlon).astype(np.float32)
    temp_C = base_C + seasonal_C + noise_C
    temp_F = temp_C * 9.0 / 5.0 + 32.0
    t2m_data[t] = temp_F

# Add ~5% missing values
mask_t2m = np.random.random((ntime, nlat, nlon)) < 0.05
t2m_data[mask_t2m] = -9999.0

t2m_var = ds.createVariable('t2m', 'f4', ('time', 'latitude', 'longitude'),
                            fill_value=np.float32(-9999.0))
t2m_var[:] = t2m_data
t2m_var.long_name = '2 metre temperature'
t2m_var.units = 'degF'
# NO standard_name
ds.sync()

# --- Variable 2: rh2m (relative humidity in %, some values exceed 100%) ---
rh_data = np.zeros((ntime, nlat, nlon), dtype=np.float32)
for t in range(ntime):
    # Higher RH in tropics, lower at poles
    base_rh = 70.0 - 20.0 * np.abs(lat_grid) / 90.0
    noise_rh = 15.0 * np.random.randn(nlat, nlon).astype(np.float32)
    rh_data[t] = base_rh + noise_rh

mask_rh = np.random.random((ntime, nlat, nlon)) < 0.05
rh_data[mask_rh] = -9999.0

rh_var = ds.createVariable('rh2m', 'f4', ('time', 'latitude', 'longitude'),
                           fill_value=np.float32(-9999.0))
rh_var[:] = rh_data
rh_var.long_name = '2 metre relative humidity'
rh_var.units = '%'
# NO standard_name
ds.sync()

# --- Variable 3: precip (precipitation in mm/day, with negative values) ---
pr_data = np.zeros((ntime, nlat, nlon), dtype=np.float32)
for t in range(ntime):
    base_mm = 5.0 * np.exp(-lat_grid ** 2 / 500.0)
    noise_mm = 2.0 * np.random.randn(nlat, nlon).astype(np.float32)
    pr_data[t] = base_mm + noise_mm  # Some values will be negative!

mask_pr = np.random.random((ntime, nlat, nlon)) < 0.05
pr_data[mask_pr] = -999.0

pr_var = ds.createVariable('precip', 'f4', ('time', 'latitude', 'longitude'),
                           fill_value=np.float32(-999.0))
pr_var[:] = pr_data
pr_var.long_name = 'total precipitation'
pr_var.units = 'mm/day'
# NO standard_name
ds.sync()

# --- Variable 4: mslp (sea level pressure in hPa) ---
psl_data = np.zeros((ntime, nlat, nlon), dtype=np.float32)
for t in range(ntime):
    base_hpa = 1013.25 - 5.0 * np.cos(np.radians(lat_grid))
    noise_hpa = 3.0 * np.random.randn(nlat, nlon).astype(np.float32)
    psl_data[t] = base_hpa + noise_hpa

mask_psl = np.random.random((ntime, nlat, nlon)) < 0.05
psl_data[mask_psl] = -999.0

psl_var = ds.createVariable('mslp', 'f4', ('time', 'latitude', 'longitude'),
                            fill_value=np.float32(-999.0))
psl_var[:] = psl_data
psl_var.long_name = 'mean sea level pressure'
psl_var.units = 'hPa'
# NO standard_name
ds.sync()

# --- Extra variable (should be ignored by cmorizer) ---
qflag = ds.createVariable('quality_flag', 'i1', ('time', 'latitude', 'longitude'),
                          fill_value=np.int8(-1))
qflag[:] = np.random.randint(0, 4, (ntime, nlat, nlon)).astype(np.int8)
qflag.long_name = 'quality control flag'
qflag.flag_values = np.array([0, 1, 2, 3], dtype=np.int8)
qflag.flag_meanings = 'good questionable bad missing'

# Minimal/wrong global attributes
ds.source = 'Raw station observations v3.2'
ds.Conventions = 'None'
ds.processing_level = 'raw'
ds.institution = 'Example Climate Data Center'

ds.sync()
ds.close()
print(f'Created raw data file: {filepath}')

# Verification: reopen and check all variables exist
ds_check = nc.Dataset(filepath, 'r')
expected_vars = ['t2m', 'rh2m', 'precip', 'mslp', 'quality_flag',
                 'time', 'latitude', 'longitude']
found_vars = list(ds_check.variables.keys())
ds_check.close()

for vname in expected_vars:
    if vname not in found_vars:
        print(f'VERIFICATION FAILED: variable {vname} not found in file!')
        print(f'Found variables: {found_vars}')
        sys.exit(1)

print(f'Verification passed: all {len(expected_vars)} variables present')
print(f'Variables: {found_vars}')
