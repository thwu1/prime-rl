#!/usr/bin/env python3
"""Generate synthetic climate data files with realistic formatting issues.

Creates 3 netCDF files covering 24 months (Jan 2000 - Dec 2001) of atmospheric
data on a 4x6 lat-lon grid. Each file has a different formatting defect that
prevents standard NCO workflow operations from succeeding.
"""
import numpy as np
import os
from netCDF4 import Dataset

os.makedirs('/app/data', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)

# Grid definition
LATS = np.array([-67.5, -22.5, 22.5, 67.5], dtype=np.float64)
LONS = np.array([30.0, 90.0, 150.0, 210.0, 270.0, 330.0], dtype=np.float64)
NLAT, NLON = len(LATS), len(LONS)

# Land mask: True = missing data (3 cells out of 24)
LAND = np.zeros((NLAT, NLON), dtype=bool)
LAND[0, 2] = True   # lat=-67.5, lon=150 (Antarctic shelf)
LAND[2, 4] = True   # lat=22.5,  lon=270 (tropical land)
LAND[3, 0] = True   # lat=67.5,  lon=30  (Scandinavian land)

FILL = -9999.0
PI = np.pi


def compute_fields(months):
    """Compute deterministic atmospheric fields for given month indices (0-based)."""
    nm = len(months)
    tas = np.full((nm, NLAT, NLON), np.nan)
    uas = np.full((nm, NLAT, NLON), np.nan)
    vas = np.full((nm, NLAT, NLON), np.nan)

    for ti, m in enumerate(months):
        for j in range(NLAT):
            for k in range(NLON):
                if not LAND[j, k]:
                    tas[ti, j, k] = (280.0
                                     + 10.0 * np.sin(2 * PI * (m % 12 + 0.5) / 12.0)
                                     + 5.0 * (LATS[j] / 90.0)
                                     + m * 0.1)
                    uas[ti, j, k] = (5.0 * np.cos(LATS[j] * PI / 180.0)
                                     + 0.5 * np.sin(2 * PI * (m % 12) / 12.0))
                    vas[ti, j, k] = (2.0 * np.sin(2 * PI * (m % 12 + 0.5) / 12.0)
                                     * np.cos(LATS[j] * PI / 180.0))
    return tas, uas, vas


def time_values(months):
    """Time coordinate as days since 2000-01-01 (approximate mid-month)."""
    return np.array([m * 30.4375 + 15.0 for m in months], dtype=np.float64)


def add_coords(ds, tv, lat_name='lat', lon_name='lon',
               lat_dim='lat', lon_dim='lon'):
    """Add time and spatial coordinate variables."""
    t = ds.createVariable('time', 'f8', ('time',))
    t.units = 'days since 2000-01-01'
    t.calendar = 'standard'
    t.axis = 'T'
    t.long_name = 'time'
    t[:] = tv

    la = ds.createVariable(lat_name, 'f8', (lat_dim,))
    la.units = 'degrees_north'
    la.long_name = 'latitude'
    la.axis = 'Y'
    la[:] = LATS

    lo = ds.createVariable(lon_name, 'f8', (lon_dim,))
    lo.units = 'degrees_east'
    lo.long_name = 'longitude'
    lo.axis = 'X'
    lo[:] = LONS


VAR_META = [
    ('tas', 'K', 'Near-Surface Air Temperature', 'air_temperature'),
    ('uas', 'm s-1', 'Eastward Near-Surface Wind', 'eastward_wind'),
    ('vas', 'm s-1', 'Northward Near-Surface Wind', 'northward_wind'),
]

# ======================================================================
# FILE A: months 0-7 (Jan-Aug 2000)
# DEFECT: _FillValue set to NaN (common Matlab/xarray export issue).
#         NCO cannot reliably detect NaN as fill → ncra averages produce NaN.
# ======================================================================
months_a = list(range(0, 8))
tas_a, uas_a, vas_a = compute_fields(months_a)

ds = Dataset('/app/data/model_200001-200008.nc', 'w', format='NETCDF4')
ds.createDimension('time', None)  # unlimited
ds.createDimension('lat', NLAT)
ds.createDimension('lon', NLON)
add_coords(ds, time_values(months_a))

for name, units, long_name, std_name in VAR_META:
    data = {'tas': tas_a, 'uas': uas_a, 'vas': vas_a}[name]
    # NaN fill value is the defect
    v = ds.createVariable(name, 'f8', ('time', 'lat', 'lon'),
                          fill_value=np.nan)
    v.units = units
    v.long_name = long_name
    v.standard_name = std_name
    v[:] = data  # NaN values at masked cells

ds.Conventions = 'CF-1.6'
ds.source = 'Synthetic climate model (group A)'
ds.close()

# ======================================================================
# FILE B: months 8-15 (Sep 2000 - Apr 2001)
# DEFECT: time dimension is FIXED (not unlimited / not a record dimension).
#         ncrcat cannot concatenate files without a record dimension.
# ======================================================================
months_b = list(range(8, 16))
tas_b, uas_b, vas_b = compute_fields(months_b)

ds = Dataset('/app/data/model_200009-200104.nc', 'w', format='NETCDF4')
ds.createDimension('time', len(months_b))  # FIXED — not unlimited!
ds.createDimension('lat', NLAT)
ds.createDimension('lon', NLON)
add_coords(ds, time_values(months_b))

for name, units, long_name, std_name in VAR_META:
    data = {'tas': tas_b, 'uas': uas_b, 'vas': vas_b}[name].copy()
    data[np.isnan(data)] = FILL
    v = ds.createVariable(name, 'f8', ('time', 'lat', 'lon'),
                          fill_value=FILL)
    v.units = units
    v.long_name = long_name
    v.standard_name = std_name
    v[:] = data

ds.Conventions = 'CF-1.6'
ds.source = 'Synthetic climate model (group B)'
ds.close()

# ======================================================================
# FILE C: months 16-23 (May-Dec 2001)
# DEFECT: Non-standard dimension and coordinate variable names.
#         Dimensions are 'y'/'x' instead of 'lat'/'lon'.
#         Coordinate variables are 'nav_lat'/'nav_lon' (NEMO ocean model style).
#         This prevents ncrcat from matching dimensions across files.
# ======================================================================
months_c = list(range(16, 24))
tas_c, uas_c, vas_c = compute_fields(months_c)

ds = Dataset('/app/data/model_200105-200112.nc', 'w', format='NETCDF4')
ds.createDimension('time', None)  # unlimited
ds.createDimension('y', NLAT)     # non-standard dim name
ds.createDimension('x', NLON)     # non-standard dim name
add_coords(ds, time_values(months_c),
           lat_name='nav_lat', lon_name='nav_lon',
           lat_dim='y', lon_dim='x')

for name, units, long_name, std_name in VAR_META:
    data = {'tas': tas_c, 'uas': uas_c, 'vas': vas_c}[name].copy()
    data[np.isnan(data)] = FILL
    v = ds.createVariable(name, 'f8', ('time', 'y', 'x'),
                          fill_value=FILL)
    v.units = units
    v.long_name = long_name
    v.standard_name = std_name
    v.coordinates = 'nav_lat nav_lon'
    v[:] = data

ds.Conventions = 'CF-1.6'
ds.source = 'Synthetic climate model (group C — NEMO-style coordinates)'
ds.close()

print("Data generation complete. Files:")
for f in sorted(os.listdir('/app/data')):
    print(f"  /app/data/{f}")
