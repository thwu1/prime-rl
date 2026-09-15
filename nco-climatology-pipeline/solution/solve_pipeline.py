#!/usr/bin/env python3

"""Process climate model data: fix NaN issues, compute climatology, derive variables."""

import os
import numpy as np
from netCDF4 import Dataset

FILL = np.float32(1.0e20)
YEARS = [2010, 2011, 2012]

# ---------------------------------------------------------------------------
# Step 1: Read all input data (raw, no auto-masking)
# ---------------------------------------------------------------------------
all_data = {}
lats = lons = None

for year in YEARS:
    ds = Dataset('/app/data/climate_{}.nc'.format(year), 'r')
    ds.set_auto_maskandscale(False)

    if lats is None:
        lats = ds.variables['latitude'][:].copy()
        lons = ds.variables['longitude'][:].copy()

    all_data[year] = {
        'tas': ds.variables['tas'][:].copy(),
        'uas': ds.variables['uas'][:].copy(),
        'vas': ds.variables['vas'][:].copy(),
    }
    ds.close()

nlat, nlon = len(lats), len(lons)
print('Loaded {} years, grid {}x{}'.format(len(YEARS), nlat, nlon))

# ---------------------------------------------------------------------------
# Step 2: Compute 12-month climatology, excluding NaN (corrupt/missing) values
# ---------------------------------------------------------------------------
clim = {}
for var in ['tas', 'uas', 'vas']:
    result = np.full((12, nlat, nlon), FILL, dtype=np.float32)
    for m in range(12):
        stack = np.array([all_data[y][var][m] for y in YEARS], dtype=np.float64)
        valid = ~np.isnan(stack)
        count = valid.sum(axis=0)
        total = np.where(valid, stack, 0.0).sum(axis=0)

        has_data = count > 0
        result[m, has_data] = (total[has_data] / count[has_data]).astype(np.float32)

    clim[var] = result

print('Computed 12-month climatology')

# ---------------------------------------------------------------------------
# Step 3: Convert temperature from Celsius to Kelvin
# ---------------------------------------------------------------------------
valid_tas = clim['tas'] != FILL
clim['tas'][valid_tas] = (clim['tas'][valid_tas].astype(np.float64) + 273.15).astype(np.float32)

print('Converted temperature to Kelvin')

# ---------------------------------------------------------------------------
# Step 4: Compute wind speed: wsp = sqrt(uas^2 + vas^2)
# ---------------------------------------------------------------------------
valid_wind = (clim['uas'] != FILL) & (clim['vas'] != FILL)
wsp = np.full((12, nlat, nlon), FILL, dtype=np.float32)
wsp[valid_wind] = np.sqrt(
    clim['uas'][valid_wind].astype(np.float64) ** 2
    + clim['vas'][valid_wind].astype(np.float64) ** 2
).astype(np.float32)

print('Derived wind speed')

# ---------------------------------------------------------------------------
# Step 5: Compute cosine-latitude area-weighted global mean of tas
# ---------------------------------------------------------------------------
cos_w = np.cos(np.deg2rad(lats)).astype(np.float64)
tas_global_mean = np.zeros(12, dtype=np.float32)

for m in range(12):
    valid = clim['tas'][m] != FILL
    weights_2d = np.broadcast_to(cos_w[:, np.newaxis], (nlat, nlon))
    weighted_vals = np.where(valid, clim['tas'][m].astype(np.float64) * weights_2d, 0.0)
    weight_sums = np.where(valid, weights_2d, 0.0)
    tas_global_mean[m] = np.float32(weighted_vals.sum() / weight_sums.sum())

print('Computed global mean temperature: {}'.format(tas_global_mean))

# ---------------------------------------------------------------------------
# Step 6: Write output netCDF file
# ---------------------------------------------------------------------------
os.makedirs('/app/output', exist_ok=True)
out = Dataset('/app/output/climatology.nc', 'w', format='NETCDF4')

out.createDimension('time', 12)
out.createDimension('lat', nlat)
out.createDimension('lon', nlon)

tv = out.createVariable('time', 'f8', ('time',))
tv.units = 'months since 2010-01-01'
tv.calendar = 'standard'
tv[:] = np.arange(12, dtype=np.float64)

latv = out.createVariable('lat', 'f8', ('lat',))
latv.units = 'degrees_north'
latv[:] = lats

lonv = out.createVariable('lon', 'f8', ('lon',))
lonv.units = 'degrees_east'
lonv[:] = lons

for vname, data, units, sn, ln in [
    ('tas', clim['tas'], 'K', 'air_temperature', 'Near-Surface Air Temperature'),
    ('uas', clim['uas'], 'm s-1', None, 'Eastward Near-Surface Wind'),
    ('vas', clim['vas'], 'm s-1', None, 'Northward Near-Surface Wind'),
    ('wsp', wsp, 'm s-1', None, 'Wind Speed'),
]:
    v = out.createVariable(vname, 'f4', ('time', 'lat', 'lon'), fill_value=FILL)
    v.units = units
    v.long_name = ln
    if sn:
        v.standard_name = sn
    v[:] = data

# tas_global_mean: no fill_value since all 12 values are always valid
gmv = out.createVariable('tas_global_mean', 'f4', ('time',), fill_value=False)
gmv.units = 'K'
gmv.long_name = 'Area-weighted Global Mean Temperature'
gmv[:] = tas_global_mean

out.Conventions = 'CF-1.6'
out.close()

print('Pipeline complete. Output: /app/output/climatology.nc')
