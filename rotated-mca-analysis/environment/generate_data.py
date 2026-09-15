"""Generate synthetic coupled climate datasets in NetCDF format.

"""
import numpy as np
import xarray as xr


def main():
    rng = np.random.default_rng(42)

    n_time = 200
    lat = np.arange(-60, 65, 10.0)   # 13 points: -60, -50, ..., 60
    lon_x = np.arange(0, 200, 10.0)  # 20 points
    lon_y = np.arange(200, 350, 10.0) # 15 points

    n_lat = len(lat)
    n_lon_x = len(lon_x)
    n_lon_y = len(lon_y)

    LAT_X, LON_X = np.meshgrid(lat, lon_x, indexing='ij')
    LAT_Y, LON_Y = np.meshgrid(lat, lon_y, indexing='ij')

    # --- spatial patterns for X field ---
    p1_x = np.sin(np.radians(LAT_X)) * np.cos(np.radians(LON_X * 2))
    p2_x = np.cos(np.radians(LAT_X * 3)) * np.sin(np.radians(LON_X))
    p3_x = np.exp(-((LAT_X - 20)**2 + (LON_X - 100)**2) / 800)

    # --- spatial patterns for Y field ---
    p1_y = np.cos(np.radians(LAT_Y * 2)) * np.sin(np.radians(LON_Y - 270))
    p2_y = np.sin(np.radians(LAT_Y)) * np.cos(np.radians(LON_Y * 2 - 500))
    p3_y = np.exp(-((LAT_Y + 15)**2 + (LON_Y - 280)**2) / 600)

    # normalise to unit Frobenius norm
    for p in [p1_x, p2_x, p3_x, p1_y, p2_y, p3_y]:
        p /= np.linalg.norm(p)

    # coupled time series
    t1 = rng.normal(0, 1, n_time)
    t2 = rng.normal(0, 1, n_time)
    t3 = rng.normal(0, 1, n_time)

    # coupling strengths
    s1, s2, s3 = 15.0, 9.0, 5.0

    # construct data fields = signal + noise
    X = (s1 * np.outer(t1, p1_x.ravel())
       + s2 * np.outer(t2, p2_x.ravel())
       + s3 * np.outer(t3, p3_x.ravel())
       + rng.normal(0, 0.5, (n_time, n_lat * n_lon_x)))
    X = X.reshape(n_time, n_lat, n_lon_x)

    Y = (s1 * np.outer(t1, p1_y.ravel())
       + s2 * np.outer(t2, p2_y.ravel())
       + s3 * np.outer(t3, p3_y.ravel())
       + rng.normal(0, 0.4, (n_time, n_lat * n_lon_y)))
    Y = Y.reshape(n_time, n_lat, n_lon_y)

    # land masks (simulate continental outlines)
    land_x = np.zeros((n_lat, n_lon_x), dtype=bool)
    land_x[0, 0:2] = True
    land_x[-1, -2:] = True

    land_y = np.zeros((n_lat, n_lon_y), dtype=bool)
    land_y[0:2, 0:3] = True
    land_y[-2:, -3:] = True

    X[:, land_x] = np.nan
    Y[:, land_y] = np.nan

    # Save as NetCDF via xarray
    ds_x = xr.Dataset(
        {'data': (['time', 'lat', 'lon'], X)},
        coords={'time': np.arange(n_time), 'lat': lat, 'lon': lon_x},
    )
    ds_x.to_netcdf('/app/data/field_x.nc', engine='scipy')

    ds_y = xr.Dataset(
        {'data': (['time', 'lat', 'lon'], Y)},
        coords={'time': np.arange(n_time), 'lat': lat, 'lon': lon_y},
    )
    ds_y.to_netcdf('/app/data/field_y.nc', engine='scipy')


if __name__ == '__main__':
    main()
