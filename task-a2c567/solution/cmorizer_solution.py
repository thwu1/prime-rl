#!/usr/bin/env python3
"""CMORizer solution: transforms raw observational NetCDF to CMOR-compliant output.

Handles 360-day calendar conversion to Gregorian, unit conversions for three
direct variables (tas, pr, psl), and derivation of specific humidity (huss)
from temperature, relative humidity, and surface pressure using the Tetens
formula for saturation vapor pressure."""
import json
import os
from datetime import datetime

import netCDF4 as nc
import numpy as np


def days_since_1950(dt):
    """Convert a datetime object to days since 1950-01-01."""
    return (dt - datetime(1950, 1, 1)).days


def calendar_360_to_gregorian_monthly(n_times, start_year=2000):
    """Convert 360-day calendar monthly data to Gregorian time coordinates.

    In a 360-day calendar each month has exactly 30 days. For monthly mean
    data, each 360-day month maps to the same-numbered Gregorian month.
    We compute Gregorian mid-month dates and calendar-aware month bounds.
    """
    midpoints = []
    bounds = []
    for t in range(n_times):
        year = start_year + t // 12
        month = (t % 12) + 1
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        mid = datetime(year, month, 15)
        midpoints.append(days_since_1950(mid))
        bounds.append([days_since_1950(start), days_since_1950(end)])
    return np.array(midpoints, dtype=np.float64), np.array(bounds, dtype=np.float64)


def compute_regular_bounds(coord, clip_min=None, clip_max=None):
    """Compute bounds for a regular-spaced coordinate array."""
    step = coord[1] - coord[0]
    bnds = np.zeros((len(coord), 2), dtype=np.float64)
    bnds[:, 0] = coord - step / 2.0
    bnds[:, 1] = coord + step / 2.0
    if clip_min is not None:
        bnds[:, 0] = np.maximum(bnds[:, 0], clip_min)
    if clip_max is not None:
        bnds[:, 1] = np.minimum(bnds[:, 1], clip_max)
    return bnds


def compute_specific_humidity(t_kelvin, rh_pct, p_pascal):
    """Compute specific humidity from temperature, relative humidity, and pressure.

    Uses the Tetens formula for saturation vapor pressure:
        es = 611.2 * exp(17.67 * Tc / (Tc + 243.5))  [Pa]
    Then:
        e = (RH/100) * es
        q = 0.622 * e / (P - 0.378 * e)   [kg/kg, dimensionless]

    RH is clipped to [0, 100] to handle supersaturation.
    """
    rh_clipped = np.clip(rh_pct, 0.0, 100.0)
    tc = t_kelvin - 273.15
    es = 611.2 * np.exp(17.67 * tc / (tc + 243.5))
    e = (rh_clipped / 100.0) * es
    q = 0.622 * e / (p_pascal - 0.378 * e)
    return q


def main():
    # Load specifications
    with open("/app/cmor_table_Amon.json") as f:
        cmor_table = json.load(f)
    with open("/app/global_attrs_spec.json") as f:
        global_spec = json.load(f)

    # Open raw data
    ds_raw = nc.Dataset("/app/raw_data/station_obs_monthly_2000-2002.nc", "r")

    # --- Fix longitude: shift from [-180, 180) to [0, 360) ---
    lon_raw = np.array(ds_raw["longitude"][:], dtype=np.float64)
    lon_new = lon_raw % 360.0
    sort_idx = np.argsort(lon_new)
    lon_new = lon_new[sort_idx]

    # --- Fix latitude: ensure float64 ---
    lat_new = np.array(ds_raw["latitude"][:], dtype=np.float64)

    # --- Fix time: convert 360-day calendar to Gregorian ---
    ntime = len(ds_raw["time"][:])
    time_new, time_bnds = calendar_360_to_gregorian_monthly(ntime)

    # --- Compute coordinate bounds ---
    lon_bnds = compute_regular_bounds(lon_new)
    lat_bnds = compute_regular_bounds(lat_new, clip_min=-90.0, clip_max=90.0)

    # --- Read all raw variables ---
    # t2m: temperature in degF
    t2m_ma = ds_raw["t2m"][:]
    t2m_mask = np.ma.getmaskarray(t2m_ma).copy()
    t2m_float = np.array(t2m_ma.data, dtype=np.float64)
    t2m_float[t2m_mask] = np.nan

    # rh2m: relative humidity in %
    rh_ma = ds_raw["rh2m"][:]
    rh_mask = np.ma.getmaskarray(rh_ma).copy()
    rh_float = np.array(rh_ma.data, dtype=np.float64)
    rh_float[rh_mask] = np.nan

    # precip: precipitation in mm/day
    pr_ma = ds_raw["precip"][:]
    pr_mask = np.ma.getmaskarray(pr_ma).copy()
    pr_float = np.array(pr_ma.data, dtype=np.float64)
    pr_float[pr_mask] = np.nan

    # mslp: sea level pressure in hPa
    psl_ma = ds_raw["mslp"][:]
    psl_mask = np.ma.getmaskarray(psl_ma).copy()
    psl_float = np.array(psl_ma.data, dtype=np.float64)
    psl_float[psl_mask] = np.nan

    # --- Convert units ---
    # tas: degF -> K
    tas_data = (t2m_float - 32.0) * 5.0 / 9.0 + 273.15

    # pr: mm/day -> kg m-2 s-1, clip negative precipitation
    pr_data = np.maximum(pr_float, 0.0) / 86400.0

    # psl: hPa -> Pa
    psl_data = psl_float * 100.0

    # --- Derive huss from T, RH, P ---
    # Combined mask: any source missing -> huss missing
    combined_mask = np.isnan(tas_data) | np.isnan(rh_float) | np.isnan(psl_data)
    huss_data = compute_specific_humidity(tas_data, rh_float, psl_data)
    huss_data[combined_mask] = np.nan
    # Clip to valid range
    huss_data = np.clip(huss_data, 0.0, 0.04)

    # --- Reorder longitude axis for all data arrays ---
    tas_data = tas_data[:, :, sort_idx]
    pr_data = pr_data[:, :, sort_idx]
    psl_data = psl_data[:, :, sort_idx]
    huss_data = huss_data[:, :, sort_idx]

    # --- Write output files ---
    variables = {
        "tas": tas_data,
        "pr": pr_data,
        "psl": psl_data,
        "huss": huss_data,
    }

    os.makedirs("/app/output", exist_ok=True)

    for cmor_name, data in variables.items():
        var_spec = cmor_table["variable_entry"][cmor_name]
        coord_specs = cmor_table["coordinate_entry"]

        # Convert to float32, replace NaN with CMOR fill value
        data_f32 = data.astype(np.float32)
        data_f32[np.isnan(data_f32)] = np.float32(1e20)

        # Build output filename
        attrs = global_spec["required_attributes"]
        filename = (
            f"{attrs['project_id']}_{attrs['dataset_id']}_"
            f"{global_spec['source_type']}_{attrs['version']}_"
            f"{global_spec['mip']}_{cmor_name}_200001-200212.nc"
        )
        filepath = os.path.join("/app/output", filename)

        # Create output NetCDF
        ds_out = nc.Dataset(filepath, "w", format="NETCDF4")

        # Dimensions (time is unlimited)
        ds_out.createDimension("time", None)
        ds_out.createDimension("latitude", len(lat_new))
        ds_out.createDimension("longitude", len(lon_new))
        ds_out.createDimension("bnds", 2)

        # --- Time coordinate ---
        time_var = ds_out.createVariable("time", "f8", ("time",))
        time_var[:] = time_new
        time_var.units = coord_specs["time"]["units"]
        time_var.calendar = coord_specs["time"]["calendar_type"]
        time_var.axis = coord_specs["time"]["axis"]
        time_var.standard_name = coord_specs["time"]["standard_name"]
        time_var.long_name = "time"
        time_var.bounds = "time_bnds"

        time_bnds_var = ds_out.createVariable("time_bnds", "f8", ("time", "bnds"))
        time_bnds_var[:] = time_bnds

        # --- Latitude coordinate ---
        lat_var = ds_out.createVariable("latitude", "f8", ("latitude",))
        lat_var[:] = lat_new
        lat_var.units = coord_specs["latitude"]["units"]
        lat_var.axis = coord_specs["latitude"]["axis"]
        lat_var.standard_name = coord_specs["latitude"]["standard_name"]
        lat_var.long_name = "latitude"
        lat_var.bounds = "latitude_bnds"

        lat_bnds_var = ds_out.createVariable("latitude_bnds", "f8", ("latitude", "bnds"))
        lat_bnds_var[:] = lat_bnds

        # --- Longitude coordinate ---
        lon_var = ds_out.createVariable("longitude", "f8", ("longitude",))
        lon_var[:] = lon_new
        lon_var.units = coord_specs["longitude"]["units"]
        lon_var.axis = coord_specs["longitude"]["axis"]
        lon_var.standard_name = coord_specs["longitude"]["standard_name"]
        lon_var.long_name = "longitude"
        lon_var.bounds = "longitude_bnds"

        lon_bnds_var = ds_out.createVariable("longitude_bnds", "f8", ("longitude", "bnds"))
        lon_bnds_var[:] = lon_bnds

        # --- Height2m scalar coordinate (for tas and huss per CMOR table) ---
        if "height2m" in var_spec.get("dimensions", ""):
            h2m_spec = coord_specs["height2m"]
            h2m_var = ds_out.createVariable("height", "f8", ())
            h2m_var[()] = float(h2m_spec["value"])
            h2m_var.units = h2m_spec["units"]
            h2m_var.axis = h2m_spec["axis"]
            h2m_var.positive = h2m_spec["positive"]
            h2m_var.standard_name = h2m_spec["standard_name"]
            h2m_var.long_name = "height"

        # --- Data variable ---
        data_var = ds_out.createVariable(
            cmor_name,
            "f4",
            ("time", "latitude", "longitude"),
            fill_value=np.float32(1e20),
        )
        data_var[:] = data_f32
        data_var.standard_name = var_spec["standard_name"]
        data_var.long_name = var_spec["long_name"]
        data_var.units = var_spec["units"]
        data_var.cell_methods = var_spec["cell_methods"]

        # --- Global attributes ---
        for attr_name, attr_val in attrs.items():
            ds_out.setncattr(attr_name, attr_val)
        ds_out.Conventions = "CF-1.7 CMIP-6.2"
        ds_out.history = f"CMORized on {datetime.now().isoformat()}"

        ds_out.close()
        print(f"Created: {filepath}")

    ds_raw.close()
    print("CMORization complete.")


if __name__ == "__main__":
    main()
