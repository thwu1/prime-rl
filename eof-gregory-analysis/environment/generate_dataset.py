"""Generate synthetic climate simulation dataset in NetCDF format."""
import numpy as np
import numpy.ma as ma
import os
import warnings

np.random.seed(42)

nx, ny, nt = 40, 60, 300

lon = np.linspace(0, 360, nx, endpoint=False)
lat = np.linspace(-87, 87, ny)
LON, LAT = np.meshgrid(lon, lat, indexing='ij')
cos_weights = np.cos(np.deg2rad(LAT))

# Mode 1: Broad equatorial pattern, period 25 time steps
spatial_1 = 4.0 * np.exp(-((LON - 180)**2) / 3000 - (LAT**2) / 400)
temporal_1 = np.cos(2 * np.pi * np.arange(nt) / 25)

# Mode 2: Meridional dipole, period 50 time steps
spatial_2 = 3.0 * np.sin(np.pi * LAT / 90) * np.cos(np.pi * LON / 180)
temporal_2 = np.sin(2 * np.pi * np.arange(nt) / 50)

# Mode 3: Zonal wave, period 60 time steps
spatial_3 = 2.0 * np.cos(2 * np.pi * LON / 120) * np.cos(np.pi * LAT / 180)
temporal_3 = np.cos(2 * np.pi * np.arange(nt) / 60)

# Mode 4: Secondary wave pattern, period 30 time steps
spatial_4 = 1.8 * np.sin(2 * np.pi * LON / 90 + np.pi / 4) * np.cos(np.pi * LAT / 90)
temporal_4 = np.sin(2 * np.pi * np.arange(nt) / 30)

field = (spatial_1[:, :, None] * temporal_1[None, None, :] +
         spatial_2[:, :, None] * temporal_2[None, None, :] +
         spatial_3[:, :, None] * temporal_3[None, None, :] +
         spatial_4[:, :, None] * temporal_4[None, None, :])

noise = np.random.normal(0, 1.0, (nx, ny, nt))
field = field + noise

# Land mask
land_mask = np.zeros((nx, ny), dtype=bool)
land_mask[5:15, 20:35] = True
land_mask[25:35, 40:55] = True
field[land_mask, :] = np.nan

# Remove temporal mean at each grid point
with warnings.catch_warnings():
    warnings.simplefilter("ignore", RuntimeWarning)
    field_mean = np.nanmean(field, axis=2, keepdims=True)
field = field - field_mean

# Gregory method time series (1D)
feedback_param = -1.2   # W/m^2/K
forcing = 4.0           # W/m^2
T_anom = np.cumsum(np.random.normal(0.015, 0.04, nt))
N_imbalance = feedback_param * T_anom + forcing + np.random.normal(0, 0.2, nt)

# --- Write as NetCDF ---
from netCDF4 import Dataset as NCDataset

# Transpose field from (lon, lat, time) to (time, lat, lon) for CF convention
tas_data = np.transpose(field, (2, 1, 0))  # (nt, ny, nx)

os.makedirs('/app/data', exist_ok=True)
nc = NCDataset('/app/data/climate_output.nc', 'w', format='NETCDF4')

nc.createDimension('time', nt)
nc.createDimension('lat', ny)
nc.createDimension('lon', nx)

lon_v = nc.createVariable('lon', 'f8', ('lon',))
lon_v[:] = lon
lon_v.units = 'degrees_east'
lon_v.long_name = 'longitude'
lon_v.standard_name = 'longitude'

lat_v = nc.createVariable('lat', 'f8', ('lat',))
lat_v[:] = lat
lat_v.units = 'degrees_north'
lat_v.long_name = 'latitude'
lat_v.standard_name = 'latitude'

time_v = nc.createVariable('time', 'f8', ('time',))
time_v[:] = np.arange(nt, dtype='f8')
time_v.units = 'days since 0001-01-01'
time_v.calendar = 'standard'
time_v.long_name = 'time'

# Surface temperature anomaly with masked land cells
# Use fill_value=np.nan so masked land cells are stored as NaN
tas_masked = ma.masked_invalid(tas_data)
tas_v = nc.createVariable('tas', 'f8', ('time', 'lat', 'lon'), fill_value=np.nan)
tas_v[:] = tas_masked
tas_v.units = 'K'
tas_v.long_name = 'Surface Temperature Anomaly'
tas_v.missing_value = np.nan

# 1D Gregory regression variables
toa_v = nc.createVariable('toa_imbalance', 'f8', ('time',))
toa_v[:] = N_imbalance
toa_v.units = 'W m-2'
toa_v.long_name = 'TOA Net Radiative Imbalance'

gmst_v = nc.createVariable('gmst_anomaly', 'f8', ('time',))
gmst_v[:] = T_anom
gmst_v.units = 'K'
gmst_v.long_name = 'Global Mean Surface Temperature Anomaly'

nc.Conventions = 'CF-1.8'
nc.title = 'Coupled Ocean-Atmosphere Model Output'
nc.close()

print("Dataset generated: /app/data/climate_output.nc")
