"""Generate synthetic SST anomaly dataset for EOF analysis task."""
import numpy as np
import xarray as xr
import os

np.random.seed(42)

ntime, nlat, nlon = 200, 30, 60
lat = np.linspace(-87, 87, nlat)
lon = np.linspace(0, 354, nlon)
time = np.arange(ntime)

LAT, LON = np.meshgrid(lat, lon, indexing='ij')

# EOF1: Tropical warming pattern (ENSO-like)
eof1 = np.exp(-(LAT ** 2 / (2 * 20 ** 2))) * np.cos(np.deg2rad(LON * 2))

# EOF2: North-south dipole (NAO-like)
eof2 = np.sin(np.deg2rad(LAT * 2)) * np.exp(-((LON - 180) ** 2 / (2 * 50 ** 2)))

# EOF3: Higher-order wave pattern
eof3 = np.cos(np.deg2rad(LAT * 3)) * np.sin(np.deg2rad(LON * 3))

eof1 /= np.linalg.norm(eof1)
eof2 /= np.linalg.norm(eof2)
eof3 /= np.linalg.norm(eof3)

pc1 = 20.0 * np.sin(2 * np.pi * time / 50)
pc2 = 12.0 * np.sin(2 * np.pi * time / 30)
pc3 = 7.5 * (np.sin(2 * np.pi * time / 20) + 0.3 * np.random.randn(ntime))

data = (
    pc1[:, None, None] * eof1[None, :, :] +
    pc2[:, None, None] * eof2[None, :, :] +
    pc3[:, None, None] * eof3[None, :, :] +
    0.6 * np.random.randn(ntime, nlat, nlon)
)

land_mask = np.zeros((nlat, nlon), dtype=bool)
land_mask[10:20, 20:35] = True
land_mask[5:7, 45:48] = True
data[:, land_mask] = np.nan

os.makedirs('/app/data', exist_ok=True)
ds = xr.Dataset({
    'sst_anomaly': xr.DataArray(
        data, dims=['time', 'lat', 'lon'],
        coords={'time': time, 'lat': lat, 'lon': lon}
    )
})
ds.to_netcdf('/app/data/sst_anomaly.nc', engine='scipy')
print(f"Dataset created: shape={data.shape}, ocean_points={(~land_mask).sum()}")
