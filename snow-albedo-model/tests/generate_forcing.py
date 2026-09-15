#!/usr/bin/env python3
"""Generate synthetic forcing data for snow model testing.

Creates a 182-day (Oct 1 - Mar 31) hourly forcing dataset for the
Reynolds Mountain East-inspired snow model benchmark.
"""

import numpy as np
import os
import netCDF4 as nc


def generate():
    output_path = '/app/data/forcing.nc'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    n_days = 182  # Oct 1 to Mar 31
    n_hours = n_days * 24  # 4368 hours
    dt = 3600.0

    time_hours = np.arange(n_hours, dtype=np.float64)
    day_frac = time_hours / 24.0
    doy = (274.0 + day_frac) % 365.0  # Oct 1 = day 274
    hour_frac = time_hours % 24

    # --- Air temperature (K) ---
    # Seasonal: coldest around Dec 21 (doy ~355)
    T_base = 269.0
    T_seasonal = -8.0 * np.cos(2 * np.pi * (doy - 355.0) / 365.0)
    T_diurnal = 4.0 * np.sin(2 * np.pi * (hour_frac - 6.0) / 24.0)
    airtemp = T_base + T_seasonal + T_diurnal

    # Warm spells: create melt-refreeze events at specific times
    for day_offset, delta_T, duration_h in [(60, 8.0, 36), (120, 10.0, 48), (160, 8.0, 48)]:
        start_h = day_offset * 24
        end_h = min(start_h + duration_h, n_hours)
        airtemp[start_h:end_h] += delta_T

    # --- Solar radiation (W/m^2) ---
    lat_rad = 43.2 * np.pi / 180.0  # Reynolds Creek, Idaho
    declination = -23.45 * np.cos(2 * np.pi * (doy + 10.0) / 365.0) * np.pi / 180.0
    hour_angle = 2 * np.pi * (hour_frac - 12.0) / 24.0
    cos_zen = (np.sin(lat_rad) * np.sin(declination) +
               np.cos(lat_rad) * np.cos(declination) * np.cos(hour_angle))
    SWRadAtm = np.maximum(0.0, 800.0 * cos_zen)

    # --- Longwave radiation (W/m^2) ---
    LWRadAtm = 230.0 + 20.0 * np.cos(2 * np.pi * (doy - 355.0) / 365.0)

    # --- Wind speed (m/s) ---
    windspd = 3.0 + 1.5 * np.sin(2 * np.pi * hour_frac / 24.0)

    # --- Pressure (Pa) — mountain site ~2000m ---
    airpres = np.full(n_hours, 80000.0)

    # --- Specific humidity (kg/kg) ---
    spechum = np.full(n_hours, 0.0020)

    # --- Precipitation (kg/m^2/s) ---
    # Events every ~8 days, each 4-7 hours, moderate rate
    pptrate = np.zeros(n_hours)
    rng = np.random.RandomState(42)
    for d in range(5, n_days, 8):
        start_h = d * 24 + rng.randint(0, 12)
        duration = 4 + rng.randint(0, 4)
        rate = 2.0e-4 + rng.uniform(-0.8e-4, 0.8e-4)
        for h in range(start_h, min(start_h + duration, n_hours)):
            pptrate[h] = rate

    # --- Write NetCDF ---
    ds = nc.Dataset(output_path, 'w', format='NETCDF4')
    ds.createDimension('time', n_hours)
    ds.createDimension('hru', 1)

    t_var = ds.createVariable('time', 'f8', ('time',))
    t_var[:] = time_hours
    t_var.units = 'hours since 2005-10-01 00:00:00'
    t_var.calendar = 'standard'

    for name, data in [('pptrate', pptrate), ('SWRadAtm', SWRadAtm),
                       ('LWRadAtm', LWRadAtm), ('airtemp', airtemp),
                       ('windspd', windspd), ('airpres', airpres),
                       ('spechum', spechum)]:
        var = ds.createVariable(name, 'f8', ('time', 'hru'))
        var[:, 0] = data

    ds.close()
    print(f"Generated forcing data: {output_path} ({n_hours} timesteps)")


if __name__ == '__main__':
    generate()
