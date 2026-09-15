"""Generate synthetic climate dataset in NetCDF format with planted EOF modes.

"""
import numpy as np
import json
import os


def main():
    rng = np.random.RandomState(42)

    n_time = 200
    n_lat = 36
    n_lon = 72

    lats = np.linspace(-85, 85, n_lat)
    lons = np.linspace(0, 355, n_lon)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    # Mode 1: ENSO-like tropical pattern
    mode1 = np.exp(-lat_grid**2 / (2 * 12**2)) * np.cos(
        2 * np.pi * lon_grid / 360
    )
    # Mode 2: NAO-like mid-latitude dipole
    mode2 = (
        np.exp(-(lat_grid - 55)**2 / (2 * 10**2))
        - np.exp(-(lat_grid - 30)**2 / (2 * 10**2))
    ) * np.exp(-(lon_grid - 340)**2 / (2 * 30**2))
    # Mode 3: PNA-like wave train
    mode3 = np.sin(np.pi * lat_grid / 60) * np.cos(
        3 * 2 * np.pi * lon_grid / 360
    )
    # Mode 4: SAM-like annular mode
    mode4 = (
        np.exp(-(lat_grid + 60)**2 / (2 * 8**2))
        - np.exp(-(lat_grid + 40)**2 / (2 * 8**2))
    )

    # Normalize spatial patterns to unit Frobenius norm
    modes = [mode1, mode2, mode3, mode4]
    for i in range(len(modes)):
        modes[i] = modes[i] / np.sqrt(np.sum(modes[i]**2))

    # Temporal patterns with distinct frequencies and amplitudes
    t = np.linspace(0, 4 * np.pi, n_time)
    t1 = 10.0 * np.sin(t) + 0.2 * rng.randn(n_time)
    t2 = 6.0 * np.cos(1.7 * t + 0.3) + 0.2 * rng.randn(n_time)
    t3 = 3.5 * np.sin(0.8 * t + 1.5) + 0.2 * rng.randn(n_time)
    t4 = 2.0 * np.cos(2.5 * t + 0.7) + 0.2 * rng.randn(n_time)

    # Center temporal patterns
    temporals = [t1, t2, t3, t4]
    for i in range(len(temporals)):
        temporals[i] = temporals[i] - temporals[i].mean()

    # Construct data matrix
    data = np.zeros((n_time, n_lat, n_lon))
    for ti, si in zip(temporals, modes):
        data += ti[:, None, None] * si[None, :, :]

    # Add spatially uncorrelated noise
    data += 0.4 * rng.randn(n_time, n_lat, n_lon)

    # Land mask (NaN values)
    land_mask = np.zeros((n_lat, n_lon), dtype=bool)
    land_mask[10:22, 33:42] = True   # Africa-like
    land_mask[6:16, 12:20] = True    # Americas north
    land_mask[22:30, 14:22] = True   # Americas south
    land_mask[24:28, 52:58] = True   # Australia-like

    data[:, land_mask] = np.nan

    # Write to NetCDF format
    os.makedirs('/app', exist_ok=True)

    from netCDF4 import Dataset as NC4Dataset

    nc = NC4Dataset('/app/climate_data.nc', 'w', format='NETCDF4')

    # Dimensions
    nc.createDimension('time', n_time)
    nc.createDimension('latitude', n_lat)
    nc.createDimension('longitude', n_lon)

    # Coordinate variables
    lat_var = nc.createVariable('latitude', 'f8', ('latitude',))
    lat_var[:] = lats
    lat_var.units = 'degrees_north'
    lat_var.long_name = 'Latitude'
    lat_var.standard_name = 'latitude'

    lon_var = nc.createVariable('longitude', 'f8', ('longitude',))
    lon_var[:] = lons
    lon_var.units = 'degrees_east'
    lon_var.long_name = 'Longitude'
    lon_var.standard_name = 'longitude'

    time_var = nc.createVariable('time', 'i4', ('time',))
    time_var[:] = np.arange(n_time)
    time_var.units = 'days since 2000-01-01'
    time_var.calendar = 'standard'
    time_var.long_name = 'Time'

    # SST anomaly (float64 for numerical precision)
    sst_var = nc.createVariable('sst_anomaly', 'f8',
                                ('time', 'latitude', 'longitude'))
    sst_var[:] = data
    sst_var.long_name = 'Sea Surface Temperature Anomaly'
    sst_var.units = 'degC'

    # Land-sea mask
    mask_var = nc.createVariable('land_mask', 'i1', ('latitude', 'longitude'))
    mask_var[:] = land_mask.astype(np.int8)
    mask_var.long_name = 'Land-Sea Mask'
    mask_var.flag_meanings = 'ocean land'

    # Global attributes
    nc.title = 'Synthetic SST Anomaly Dataset for EOF Analysis'
    nc.source = 'Generated with 4 planted EOF modes (ENSO, NAO, PNA, SAM)'
    nc.Conventions = 'CF-1.8'
    nc.preprocessing_notes = (
        'Area weighting should account for grid cell area variation '
        'with latitude. Variance normalization should use unbiased estimator.'
    )

    nc.close()

    # Save task configuration
    config = {
        "n_modes": 10,
        "n_rotate": 6,
        "rotation_power": 2,
    }
    with open('/app/task_config.json', 'w') as f:
        json.dump(config, f, indent=2)


if __name__ == '__main__':
    main()
