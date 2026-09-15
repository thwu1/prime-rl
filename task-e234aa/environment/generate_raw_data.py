"""Generate synthetic raw observational climate data with non-standard conventions."""
import numpy as np
import netCDF4 as nc
from datetime import datetime, timedelta
import os

os.makedirs('/app/raw_data', exist_ok=True)

np.random.seed(42)

nlat, nlon, ntime = 36, 72, 24

# Descending latitudes (non-standard for CMOR which requires S->N)
lats = np.linspace(87.5, -87.5, nlat)
# Longitude -180..175 (non-standard: CMOR requires 0..360)
lons = np.linspace(-180, 175, nlon)

# Time: hours since 2000-01-01 00:00:00 (monthly midpoints)
time_vals = []
for i in range(ntime):
    year = 2000 + i // 12
    month = (i % 12) + 1
    month_start = datetime(year, month, 1)
    if month == 12:
        month_end = datetime(year + 1, 1, 1)
    else:
        month_end = datetime(year, month + 1, 1)
    midpoint = month_start + (month_end - month_start) / 2
    hours = (midpoint - datetime(2000, 1, 1)).total_seconds() / 3600.0
    time_vals.append(hours)
time_vals = np.array(time_vals)

# Build coordinate grids
lat_grid, lon_grid = np.meshgrid(lats, lons, indexing='ij')

# ---- Temperature in Celsius (non-standard: CMOR requires Kelvin) ----
temp = np.zeros((ntime, nlat, nlon))
for t in range(ntime):
    month = (t % 12) + 1
    seasonal = 10.0 * np.sin(2.0 * np.pi * month / 12.0) * lat_grid / 90.0
    temp[t] = 25.0 - 50.0 * np.abs(lat_grid) / 90.0 + seasonal
temp += np.random.normal(0, 1.0, temp.shape)

# ---- Dewpoint temperature in Celsius ----
# Dewpoint depression depends on latitude (drier at poles, humid at equator)
d2m = np.zeros((ntime, nlat, nlon))
for t in range(ntime):
    depression = 3.0 + 12.0 * np.abs(lat_grid) / 90.0
    d2m[t] = temp[t] - depression
d2m += np.random.normal(0, 0.5, d2m.shape)

# ---- Sea level pressure in hPa (non-standard: CMOR requires Pa) ----
psl = np.zeros((ntime, nlat, nlon))
for t in range(ntime):
    psl[t] = 1013.25 + 20.0 * np.sin(np.radians(lat_grid))
psl += np.random.normal(0, 3.0, psl.shape)

# ---- Precipitation: monthly values accumulated per calendar year ----
# Monthly precipitation in m/month
precip_monthly = np.zeros((ntime, nlat, nlon))
for t in range(ntime):
    precip_monthly[t] = np.maximum(0, 0.005 - 0.004 * np.abs(lat_grid) / 90.0)
precip_monthly += np.abs(np.random.normal(0, 0.0005, precip_monthly.shape))

# Accumulate within each calendar year
tp_acc = np.zeros((ntime, nlat, nlon))
for t in range(ntime):
    month = (t % 12) + 1
    if month == 1:
        tp_acc[t] = precip_monthly[t]
    else:
        tp_acc[t] = tp_acc[t - 1] + precip_monthly[t]

# ---- Quality flags (uint8, bit-packed) ----
# bit 0 (0x01): sensor malfunction
# bit 1 (0x02): out-of-range value
# bit 2 (0x04): spatially interpolated
# bit 3 (0x08): suspect value
qf_t2m = np.zeros((ntime, nlat, nlon), dtype=np.uint8)
qf_d2m = np.zeros((ntime, nlat, nlon), dtype=np.uint8)
qf_mslp = np.zeros((ntime, nlat, nlon), dtype=np.uint8)
qf_tp = np.zeros((ntime, nlat, nlon), dtype=np.uint8)

# t2m quality flags
qf_t2m[2, 5, 10] = 0x01    # sensor malfunction
qf_t2m[4, 20, 50] = 0x02   # out-of-range
qf_t2m[3, 8, 16] = 0x04    # interpolated (should NOT be masked)
qf_t2m[10, 22, 45] = 0x05  # sensor malfunction + interpolated -> mask
qf_t2m[8, 15, 30] = 0x01   # sensor malfunction
qf_t2m[16, 28, 55] = 0x08  # suspect (should NOT be masked)

# d2m quality flags
qf_d2m[3, 10, 20] = 0x01   # sensor malfunction -> affects huss
qf_d2m[5, 14, 28] = 0x04   # interpolated -> should NOT mask huss
qf_d2m[11, 20, 40] = 0x02  # out-of-range -> affects huss

# mslp quality flags
qf_mslp[6, 12, 25] = 0x02  # out-of-range
qf_mslp[7, 18, 35] = 0x03  # sensor malfunction + out-of-range
qf_mslp[9, 15, 40] = 0x02  # out-of-range -> affects huss

# tp quality flags
qf_tp[5, 20, 35] = 0x01    # sensor malfunction
qf_tp[14, 10, 50] = 0x02   # out-of-range

# ---- Insert missing values encoded as -9999 ----
temp[0, 0, 0] = -9999.0
temp[5, 10, 20] = -9999.0
temp[11, 17, 35] = -9999.0
temp[23, 35, 71] = -9999.0

d2m[0, 0, 0] = -9999.0
d2m[7, 12, 25] = -9999.0

psl[3, 5, 10] = -9999.0
psl[15, 25, 50] = -9999.0

tp_acc[0, 0, 0] = -9999.0
tp_acc[20, 30, 60] = -9999.0

# ---- Write NetCDF4 ----
ds = nc.Dataset('/app/raw_data/SynthObs_raw.nc', 'w', format='NETCDF4')
ds.createDimension('time', None)
ds.createDimension('latitude', nlat)
ds.createDimension('longitude', nlon)

tv = ds.createVariable('time', 'f8', ('time',))
tv.units = 'hours since 2000-01-01 00:00:00'
tv.calendar = 'standard'
tv.long_name = 'time'
tv[:] = time_vals

la = ds.createVariable('latitude', 'f8', ('latitude',))
la.units = 'degrees_north'
la.long_name = 'latitude'
la[:] = lats

lo = ds.createVariable('longitude', 'f8', ('longitude',))
lo.units = 'degrees_east'
lo.long_name = 'longitude'
lo[:] = lons

t2m_var = ds.createVariable('t2m', 'f8', ('time', 'latitude', 'longitude'),
                             fill_value=-9999.0)
t2m_var.long_name = '2 metre temperature'
t2m_var.units = 'C'
t2m_var[:] = temp

d2m_var = ds.createVariable('d2m', 'f8', ('time', 'latitude', 'longitude'),
                             fill_value=-9999.0)
d2m_var.long_name = '2 metre dewpoint temperature'
d2m_var.units = 'C'
d2m_var[:] = d2m

mslp_var = ds.createVariable('mslp', 'f8', ('time', 'latitude', 'longitude'),
                              fill_value=-9999.0)
mslp_var.long_name = 'Mean sea level pressure'
mslp_var.units = 'hPa'
mslp_var[:] = psl

tp_var = ds.createVariable('tp_acc', 'f8', ('time', 'latitude', 'longitude'),
                            fill_value=-9999.0)
tp_var.long_name = 'Total precipitation (accumulated per calendar year)'
tp_var.units = 'm'
tp_var[:] = tp_acc

for name, data in [('qf_t2m', qf_t2m), ('qf_d2m', qf_d2m),
                    ('qf_mslp', qf_mslp), ('qf_tp', qf_tp)]:
    qv = ds.createVariable(name, 'u1', ('time', 'latitude', 'longitude'))
    qv.long_name = 'Quality flags for ' + name[3:]
    qv.flag_masks = np.array([1, 2, 4, 8], dtype=np.uint8)
    qv.flag_meanings = 'sensor_malfunction out_of_range spatially_interpolated suspect'
    qv[:] = data

ds.source = 'Synthetic observational dataset'
ds.history = 'Created for CMORization benchmarking'
ds.Conventions = 'None'
ds.close()

print('Raw data generated: /app/raw_data/SynthObs_raw.nc')
