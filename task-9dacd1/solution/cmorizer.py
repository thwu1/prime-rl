#!/usr/bin/env python3
"""
CMORizer for SYNOBS synthetic observational dataset.

Converts raw observational NetCDF data to CMOR-compliant format:
- Direct variables: tas (degC->K), pr (mm/day->kg m-2 s-1)
- Derived variables:
    psl: sea-level pressure via barometric reduction from surface pressure,
         temperature, and orography
    huss: specific humidity via Magnus formula from dewpoint temperature
          and surface pressure
- Quality control: bit-flag QC exclusion
- Coordinate transforms: lon -180..180 -> 0..360, lat descending -> ascending
- Time conversion to days since 1950-1-1 00:00:00
- Coordinate bounds, scalar coordinates, CMOR metadata, CF-1.7 compliance
"""

import json
import os
from datetime import datetime

import netCDF4 as nc
import numpy as np
import yaml

# Physical constants
G = 9.80665       # m/s^2
RD = 287.05       # J/(kg*K), specific gas constant for dry air


def load_config():
    with open("/app/cmor_table.json") as f:
        table = json.load(f)
    with open("/app/cmor_config.yml") as f:
        config = yaml.safe_load(f)
    return config, table


def convert_time(time_var):
    source_units = time_var.units
    source_cal = getattr(time_var, "calendar", "standard")
    dates = nc.num2date(time_var[:], source_units, calendar=source_cal)
    target_units = "days since 1950-1-1 00:00:00"
    target_cal = "gregorian"
    new_times = nc.date2num(dates, target_units, calendar=target_cal)
    return new_times, target_units, target_cal, dates


def compute_time_bounds(times, dates):
    target_units = "days since 1950-1-1 00:00:00"
    target_cal = "gregorian"
    bounds = np.zeros((len(times), 2), dtype=np.float64)
    for i, d in enumerate(dates):
        year, month = d.year, d.month
        start = datetime(year, month, 1)
        bounds[i, 0] = nc.date2num(start, target_units, calendar=target_cal)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        bounds[i, 1] = nc.date2num(end, target_units, calendar=target_cal)
    return bounds


def shift_longitude_0_360(lon, *arrays):
    """Shift longitude from -180..180 to 0..360 and reorder all arrays."""
    new_lon = np.where(lon < 0, lon + 360.0, lon)
    sort_idx = np.argsort(new_lon)
    new_lon = new_lon[sort_idx]
    result = []
    for arr in arrays:
        if arr.ndim == 2:
            result.append(arr[:, sort_idx])
        elif arr.ndim == 3:
            result.append(arr[:, :, sort_idx])
        else:
            result.append(arr)
    return new_lon, sort_idx, result


def flip_latitude_ascending(lat, *arrays):
    """Flip latitude and all arrays if latitude is descending."""
    if lat[0] > lat[-1]:
        lat = lat[::-1].copy()
        result = []
        for arr in arrays:
            if arr.ndim == 2:
                result.append(arr[::-1, :].copy())
            elif arr.ndim == 3:
                result.append(arr[:, ::-1, :].copy())
            else:
                result.append(arr)
        return lat, result
    return lat, list(arrays)


def compute_coord_bounds(coord):
    n = len(coord)
    bounds = np.zeros((n, 2), dtype=np.float64)
    for i in range(n):
        if i == 0:
            half_below = (coord[1] - coord[0]) / 2.0
        else:
            half_below = (coord[i] - coord[i - 1]) / 2.0
        if i == n - 1:
            half_above = (coord[i] - coord[i - 1]) / 2.0
        else:
            half_above = (coord[i + 1] - coord[i]) / 2.0
        bounds[i, 0] = coord[i] - half_below
        bounds[i, 1] = coord[i] + half_above
    # Clamp latitude bounds
    if coord[0] < 0 and coord[-1] > 0:
        bounds = np.clip(bounds, -90.0, 90.0)
    return bounds


def compute_huss(td2m_celsius, sp_hpa):
    """Compute specific humidity from dewpoint temperature and surface pressure.

    Uses the Magnus/Tetens formula for saturation vapor pressure at dewpoint,
    then converts to specific humidity.

    Parameters:
        td2m_celsius: dewpoint temperature in degrees Celsius
        sp_hpa: surface pressure in hPa

    Returns:
        specific humidity in kg/kg (dimensionless)
    """
    # Saturation vapor pressure at dewpoint = actual vapor pressure
    e = 6.112 * np.exp(17.67 * td2m_celsius / (td2m_celsius + 243.5))  # hPa
    # Specific humidity from vapor pressure and total pressure
    huss = 0.622 * e / (sp_hpa - 0.378 * e)
    return huss


def compute_psl(sp_hpa, t2m_celsius, orog_m):
    """Reduce surface pressure to mean sea level using barometric formula.

    Parameters:
        sp_hpa: surface pressure in hPa
        t2m_celsius: near-surface temperature in degrees Celsius
        orog_m: surface altitude in meters (2D array broadcast to 3D)

    Returns:
        sea-level pressure in Pa
    """
    T_kelvin = t2m_celsius + 273.15
    # Broadcast orog to 3D if needed
    if orog_m.ndim == 2:
        orog_3d = orog_m[np.newaxis, :, :]
    else:
        orog_3d = orog_m
    # Barometric formula
    psl_hpa = sp_hpa * np.exp(G * orog_3d / (RD * T_kelvin))
    return psl_hpa * 100.0  # convert to Pa


def write_output(filepath, short_name, data, var_spec, config,
                 lat, lon, new_times, time_units, time_cal,
                 time_bounds, lat_bounds, lon_bounds):
    """Write a single CMOR-compliant NetCDF output file."""
    attrs = config["attributes"]
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    out = nc.Dataset(filepath, "w", format="NETCDF4")

    # Dimensions
    out.createDimension("time", None)
    out.createDimension("lat", len(lat))
    out.createDimension("lon", len(lon))
    out.createDimension("bnds", 2)

    # Time
    time_out = out.createVariable("time", "f8", ("time",))
    time_out.units = time_units
    time_out.calendar = time_cal
    time_out.standard_name = "time"
    time_out.long_name = "time"
    time_out.bounds = "time_bnds"
    time_out[:] = new_times

    time_bnds = out.createVariable("time_bnds", "f8", ("time", "bnds"))
    time_bnds[:] = time_bounds

    # Latitude
    lat_out = out.createVariable("lat", "f8", ("lat",))
    lat_out.units = "degrees_north"
    lat_out.standard_name = "latitude"
    lat_out.long_name = "latitude"
    lat_out.bounds = "lat_bnds"
    lat_out[:] = lat

    lat_bnds_out = out.createVariable("lat_bnds", "f8", ("lat", "bnds"))
    lat_bnds_out[:] = lat_bounds

    # Longitude
    lon_out = out.createVariable("lon", "f8", ("lon",))
    lon_out.units = "degrees_east"
    lon_out.standard_name = "longitude"
    lon_out.long_name = "longitude"
    lon_out.bounds = "lon_bnds"
    lon_out[:] = lon

    lon_bnds_out = out.createVariable("lon_bnds", "f8", ("lon", "bnds"))
    lon_bnds_out[:] = lon_bounds

    # Scalar coordinates
    if "scalar_coordinates" in var_spec:
        sc = var_spec["scalar_coordinates"]
        if "height" in sc:
            h = out.createVariable("height", "f8", ())
            h.units = "m"
            h.standard_name = "height"
            h.long_name = "height"
            h.positive = "up"
            h[...] = sc["height"]

    # Data variable
    data_var = out.createVariable(
        short_name, "f4", ("time", "lat", "lon"),
        fill_value=np.float32(1e20),
    )
    data_var.units = var_spec["units"]
    data_var.standard_name = var_spec["standard_name"]
    data_var.long_name = var_spec["long_name"]
    if var_spec.get("cell_methods"):
        data_var.cell_methods = var_spec["cell_methods"]
    data_var[:] = data

    # Global attributes
    out.title = f"{attrs['dataset_id']} data reformatted for ESMValTool"
    out.source = attrs["source"]
    out.project_id = attrs["project_id"]
    out.dataset_id = attrs["dataset_id"]
    out.version = attrs["version"]
    out.tier = str(attrs["tier"])
    out.comment = attrs.get("comment", "")
    out.Conventions = "CF-1.7"
    out.history = f"CMORized on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"

    out.close()
    print(f"  Written: {filepath}")


def main():
    print("Loading configuration...")
    config, table = load_config()

    # Open raw data
    raw_path = os.path.join("/app/raw_data", config["filename"])
    print(f"Opening raw data: {raw_path}")
    raw = nc.Dataset(raw_path, "r")

    # Read all raw data
    t2m = raw.variables["t2m"][:].copy()
    td2m = raw.variables["td2m"][:].copy()
    tp = raw.variables["tp"][:].copy()
    sp = raw.variables["sp"][:].copy()
    orog = raw.variables["orog"][:].copy()
    qc_flag = raw.variables["qc_flag"][:].copy()

    lat_raw = (raw.variables["latitude"][:]
               if "latitude" in raw.variables
               else raw.variables["lat"][:]).copy()
    lon_raw = (raw.variables["longitude"][:]
               if "longitude" in raw.variables
               else raw.variables["lon"][:]).copy()
    time_var = raw.variables["time"]

    # Quality control mask: any flag bit set -> exclude
    bad_mask = qc_flag != 0
    print(f"  QC: {np.count_nonzero(bad_mask)} flagged observations "
          f"out of {bad_mask.size} total")

    # Coordinate transforms
    print("Applying coordinate transforms...")

    # Longitude shift
    lon, sort_idx, shifted = shift_longitude_0_360(
        lon_raw, t2m, td2m, tp, sp, orog, qc_flag
    )
    t2m, td2m, tp, sp, orog, qc_flag = shifted
    bad_mask = qc_flag != 0

    # Latitude flip
    lat, flipped = flip_latitude_ascending(
        lat_raw, t2m, td2m, tp, sp, orog, qc_flag
    )
    t2m, td2m, tp, sp, orog, qc_flag = flipped
    bad_mask = qc_flag != 0

    # Time conversion
    print("Converting time...")
    new_times, time_units, time_cal, dates = convert_time(time_var)

    raw.close()

    # Compute bounds
    print("Computing coordinate bounds...")
    lat_bounds = compute_coord_bounds(lat.astype(np.float64))
    lon_bounds = compute_coord_bounds(lon.astype(np.float64))
    time_bounds = compute_time_bounds(new_times, dates)

    lat = lat.astype(np.float64)
    lon = lon.astype(np.float64)

    out_dir = "/app/output"
    attrs = config["attributes"]
    template = config["output_filename_template"]

    start_date = f"{dates[0].year:04d}{dates[0].month:02d}"
    end_date = f"{dates[-1].year:04d}{dates[-1].month:02d}"

    # Process each CMOR target variable
    for short_name, var_spec in table["variables"].items():
        print(f"\nProcessing: {short_name}")

        # Compute output data
        if short_name == "tas":
            data = t2m + 273.15
        elif short_name == "pr":
            data = tp / 86400.0
            data = np.maximum(data, 0.0)
        elif short_name == "psl":
            data = compute_psl(sp, t2m, orog)
        elif short_name == "huss":
            data = compute_huss(td2m, sp)
        else:
            print(f"  WARNING: Unknown variable {short_name}, skipping")
            continue

        # Apply QC mask
        data = np.where(bad_mask, np.float32(1e20), data)

        # Convert to float32
        data = data.astype(np.float32)

        # Re-mask with proper fill value (in case of float conversion issues)
        data[bad_mask] = np.float32(1e20)

        # Create masked array for netCDF4 output
        data = np.ma.array(data, mask=bad_mask)

        # Build filename
        filename = template.format(
            project_id=attrs["project_id"],
            dataset_id=attrs["dataset_id"],
            type=attrs["type"],
            version=attrs["version"],
            mip=attrs["mip"],
            variable=short_name,
            start_date=start_date,
            end_date=end_date,
        )
        filepath = os.path.join(out_dir, filename)

        write_output(filepath, short_name, data, var_spec, config,
                     lat, lon, new_times, time_units, time_cal,
                     time_bounds, lat_bounds, lon_bounds)

    print("\nCMORization complete.")


if __name__ == "__main__":
    main()
