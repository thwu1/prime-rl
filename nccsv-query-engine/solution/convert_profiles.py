#!/usr/bin/env python3
"""
Convert NCCSV CTD profile data to CF-1.8 compliant NetCDF-4 with
timeSeriesProfile discrete sampling geometry, QARTOD quality control,
UNESCO pressure-to-depth conversion, and ERDDAP datasets.xml configuration.
"""


import csv
import math
import os
from collections import OrderedDict
from datetime import datetime, timezone
from io import StringIO

import netCDF4
import numpy as np

NCCSV_FILE = "/app/data/ocean_profiles.nccsv"
NC_OUTPUT = "/app/output/profiles.nc"
XML_OUTPUT = "/app/output/erddap_config.xml"

# QARTOD thresholds for temperature
GROSS_RANGE_FAIL = (-2.5, 40.0)
GROSS_RANGE_SUSPECT = (1.0, 32.0)
SPIKE_FAIL_THRESHOLD = 6.0
SPIKE_SUSPECT_THRESHOLD = 2.0


def parse_nccsv(filepath):
    """Parse NCCSV file into global attrs, variable metadata, and data rows."""
    global_attrs = OrderedDict()
    variables = OrderedDict()
    data_rows = []

    with open(filepath, "r") as f:
        content = f.read()

    lines = content.strip().split("\n")
    in_metadata = True
    header = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "*END_METADATA*":
            in_metadata = False
            continue
        if in_metadata:
            parts = list(next(csv.reader(StringIO(stripped))))
            if len(parts) < 3:
                continue
            var_name, attr_name = parts[0], parts[1]
            attr_value = parts[2] if len(parts) > 2 else ""
            if var_name == "*GLOBAL*":
                global_attrs[attr_name] = attr_value
            else:
                if var_name not in variables:
                    variables[var_name] = {
                        "data_type": "String",
                        "attrs": OrderedDict(),
                    }
                if attr_name == "*DATA_TYPE*":
                    variables[var_name]["data_type"] = attr_value
                else:
                    variables[var_name]["attrs"][attr_name] = attr_value
        elif header is None:
            header = list(next(csv.reader(StringIO(stripped))))
        else:
            values = list(next(csv.reader(StringIO(stripped))))
            row = dict(zip(header, values))
            data_rows.append(row)

    return global_attrs, variables, data_rows


def depth_from_pressure(pressure_dbar, latitude_deg):
    """UNESCO 1983 (Fofonoff & Millard) pressure to depth conversion.

    Parameters
    ----------
    pressure_dbar : float
        Sea water pressure in decibars.
    latitude_deg : float
        Latitude in decimal degrees.

    Returns
    -------
    float
        Depth in meters (positive downward).
    """
    x = math.sin(math.radians(latitude_deg))
    x = x * x
    gr = (
        9.780318 * (1.0 + (5.2788e-3 + 2.36e-5 * x) * x)
        + 1.092e-6 * pressure_dbar
    )
    depth = (
        ((-1.82e-15 * pressure_dbar + 2.279e-10) * pressure_dbar - 2.2512e-5)
        * pressure_dbar
        + 9.72659
    ) * pressure_dbar
    return depth / gr


def iso_to_epoch(time_str):
    """Convert ISO 8601 time string to seconds since 1970-01-01T00:00:00Z."""
    dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
    dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def qartod_gross_range(temp):
    """QARTOD gross range test for temperature.

    Returns: 1=pass, 3=suspect, 4=fail, 9=missing
    """
    if temp is None:
        return 9
    if temp < GROSS_RANGE_FAIL[0] or temp > GROSS_RANGE_FAIL[1]:
        return 4
    if temp < GROSS_RANGE_SUSPECT[0] or temp > GROSS_RANGE_SUSPECT[1]:
        return 3
    return 1


def qartod_spike_test(temps, idx):
    """QARTOD spike test for temperature at index idx within a profile.

    Returns: 1=pass, 2=not_evaluated, 3=suspect, 4=fail, 9=missing
    """
    if temps[idx] is None:
        return 9
    n = len(temps)
    if idx == 0 or idx == n - 1:
        return 2  # endpoints not evaluated
    if temps[idx - 1] is None or temps[idx + 1] is None:
        return 2  # adjacent missing, not evaluated
    spike_val = abs(temps[idx] - (temps[idx - 1] + temps[idx + 1]) / 2.0)
    if spike_val > SPIKE_FAIL_THRESHOLD:
        return 4
    if spike_val > SPIKE_SUSPECT_THRESHOLD:
        return 3
    return 1


def create_netcdf(nc_path, global_attrs, variables, data_rows):
    """Create CF-1.8 NetCDF-4 with timeSeriesProfile DSG ragged array."""

    # Organize data into stations and profiles
    stations = OrderedDict()
    profiles = OrderedDict()

    for row in data_rows:
        sid = row["station_id"]
        pid = row["profile_id"]
        if sid not in stations:
            stations[sid] = {
                "lat": float(row["latitude"]),
                "lon": float(row["longitude"]),
            }
        if pid not in profiles:
            profiles[pid] = {
                "station_id": sid,
                "time": row["time"],
                "obs": [],
            }

        t_val = (
            None
            if row["temperature"] in ("NaN", "")
            else float(row["temperature"])
        )
        s_val = (
            None
            if row["salinity"] in ("NaN", "")
            else float(row["salinity"])
        )
        p_val = float(row["pressure"])

        profiles[pid]["obs"].append(
            {
                "pressure": p_val,
                "temperature": t_val,
                "salinity": s_val,
            }
        )

    station_names = list(stations.keys())
    profile_ids = list(profiles.keys())
    n_stations = len(station_names)
    n_profiles = len(profile_ids)
    n_obs = sum(len(profiles[pid]["obs"]) for pid in profile_ids)

    os.makedirs(os.path.dirname(nc_path), exist_ok=True)

    ds = netCDF4.Dataset(nc_path, "w", format="NETCDF4")

    # ── Dimensions ────────────────────────────────────────────────
    ds.createDimension("station", n_stations)
    ds.createDimension("profile", n_profiles)
    ds.createDimension("obs", n_obs)

    # ── Global attributes ─────────────────────────────────────────
    ds.Conventions = "CF-1.8, ACDD-1.3"
    ds.featureType = "timeSeriesProfile"
    ds.title = global_attrs.get("title", "")
    ds.summary = global_attrs.get("summary", "")
    ds.institution = global_attrs.get("institution", "")
    ds.source = global_attrs.get("source", "")
    ds.cdm_data_type = "TimeSeriesProfile"
    ds.cdm_timeseries_variables = "station_id, latitude, longitude"
    ds.cdm_profile_variables = "profile_id, time"

    # ── Station-level variables ───────────────────────────────────
    station_id_var = ds.createVariable("station_id", str, ("station",))
    station_id_var.long_name = "Station Identifier"
    station_id_var.cf_role = "timeseries_id"

    lat_var = ds.createVariable("latitude", "f8", ("station",))
    lat_var.standard_name = "latitude"
    lat_var.long_name = "Latitude"
    lat_var.units = "degrees_north"
    lat_var.axis = "Y"

    lon_var = ds.createVariable("longitude", "f8", ("station",))
    lon_var.standard_name = "longitude"
    lon_var.long_name = "Longitude"
    lon_var.units = "degrees_east"
    lon_var.axis = "X"

    # ── Profile-level variables ───────────────────────────────────
    profile_id_var = ds.createVariable("profile_id", str, ("profile",))
    profile_id_var.long_name = "Profile Identifier"
    profile_id_var.cf_role = "profile_id"

    time_var = ds.createVariable("time", "f8", ("profile",))
    time_var.standard_name = "time"
    time_var.long_name = "Time"
    time_var.units = "seconds since 1970-01-01T00:00:00Z"
    time_var.calendar = "gregorian"
    time_var.axis = "T"

    station_index_var = ds.createVariable("stationIndex", "i4", ("profile",))
    station_index_var.long_name = "index of station for this profile"
    station_index_var.instance_dimension = "station"

    row_size_var = ds.createVariable("row_size", "i4", ("profile",))
    row_size_var.long_name = "number of observations per profile"
    row_size_var.sample_dimension = "obs"

    # ── Observation-level variables ───────────────────────────────
    fill_f4 = np.float32(netCDF4.default_fillvals["f4"])
    coord_str = "time latitude longitude depth"

    pressure_var = ds.createVariable(
        "pressure", "f4", ("obs",), fill_value=fill_f4
    )
    pressure_var.standard_name = "sea_water_pressure"
    pressure_var.long_name = "Sea Water Pressure"
    pressure_var.units = "dbar"
    pressure_var.coordinates = coord_str

    depth_var = ds.createVariable(
        "depth", "f4", ("obs",), fill_value=fill_f4
    )
    depth_var.standard_name = "depth"
    depth_var.long_name = "Depth"
    depth_var.units = "m"
    depth_var.positive = "down"
    depth_var.axis = "Z"

    temp_var = ds.createVariable(
        "temperature", "f4", ("obs",), fill_value=fill_f4
    )
    temp_var.standard_name = "sea_water_temperature"
    temp_var.long_name = "Sea Water Temperature"
    temp_var.units = "degree_C"
    temp_var.coordinates = coord_str
    temp_var.ancillary_variables = (
        "temperature_gross_range_qc temperature_spike_qc"
    )

    sal_var = ds.createVariable(
        "salinity", "f4", ("obs",), fill_value=fill_f4
    )
    sal_var.standard_name = "sea_water_practical_salinity"
    sal_var.long_name = "Sea Water Practical Salinity"
    sal_var.units = "PSU"
    sal_var.coordinates = coord_str

    # ── QC variables ──────────────────────────────────────────────
    fill_i1 = np.int8(netCDF4.default_fillvals["i1"])

    gross_qc_var = ds.createVariable(
        "temperature_gross_range_qc", "i1", ("obs",), fill_value=fill_i1
    )
    gross_qc_var.long_name = "QARTOD Gross Range Test for Temperature"
    gross_qc_var.flag_values = np.array([1, 2, 3, 4, 9], dtype=np.int8)
    gross_qc_var.flag_meanings = "pass not_evaluated suspect fail missing"
    gross_qc_var.references = "QARTOD"

    spike_qc_var = ds.createVariable(
        "temperature_spike_qc", "i1", ("obs",), fill_value=fill_i1
    )
    spike_qc_var.long_name = "QARTOD Spike Test for Temperature"
    spike_qc_var.flag_values = np.array([1, 2, 3, 4, 9], dtype=np.int8)
    spike_qc_var.flag_meanings = "pass not_evaluated suspect fail missing"
    spike_qc_var.references = "QARTOD"

    # ── Write station data ────────────────────────────────────────
    for i, sname in enumerate(station_names):
        station_id_var[i] = sname
        lat_var[i] = stations[sname]["lat"]
        lon_var[i] = stations[sname]["lon"]

    # ── Write profile and observation data ────────────────────────
    obs_offset = 0
    for pi, pid in enumerate(profile_ids):
        prof = profiles[pid]
        st_idx = station_names.index(prof["station_id"])
        lat = stations[prof["station_id"]]["lat"]

        profile_id_var[pi] = pid
        time_var[pi] = iso_to_epoch(prof["time"])
        station_index_var[pi] = st_idx
        row_size_var[pi] = len(prof["obs"])

        # Collect temperature values for spike test
        temps = [obs["temperature"] for obs in prof["obs"]]

        for oi, obs in enumerate(prof["obs"]):
            idx = obs_offset + oi

            pressure_var[idx] = obs["pressure"]
            depth_var[idx] = depth_from_pressure(obs["pressure"], lat)

            if obs["temperature"] is None:
                temp_var[idx] = fill_f4
            else:
                temp_var[idx] = obs["temperature"]

            if obs["salinity"] is None:
                sal_var[idx] = fill_f4
            else:
                sal_var[idx] = obs["salinity"]

            # QC flags
            gross_qc_var[idx] = qartod_gross_range(obs["temperature"])
            spike_qc_var[idx] = qartod_spike_test(temps, oi)

        obs_offset += len(prof["obs"])

    ds.close()


def create_datasets_xml(xml_path):
    """Generate ERDDAP datasets.xml fragment for EDDTableFromNcCFFiles."""
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)

    var_specs = [
        ("station_id", "String"),
        ("time", "double"),
        ("latitude", "double"),
        ("longitude", "double"),
        ("profile_id", "String"),
        ("depth", "float"),
        ("pressure", "float"),
        ("temperature", "float"),
        ("salinity", "float"),
        ("temperature_gross_range_qc", "byte"),
        ("temperature_spike_qc", "byte"),
    ]

    dv_blocks = []
    for src_name, dtype in var_specs:
        block = (
            "    <dataVariable>\n"
            f"        <sourceName>{src_name}</sourceName>\n"
            f"        <dataType>{dtype}</dataType>\n"
            "    </dataVariable>"
        )
        dv_blocks.append(block)

    dv_str = "\n".join(dv_blocks)

    xml_content = (
        '<dataset type="EDDTableFromNcCFFiles" datasetID="ccs_ctd_profiles"'
        ' active="true">\n'
        "    <reloadEveryNMinutes>10080</reloadEveryNMinutes>\n"
        "    <fileDir>/data/netcdf/</fileDir>\n"
        "    <fileNameRegex>profiles\\.nc</fileNameRegex>\n"
        "    <recursive>false</recursive>\n"
        "    <pathRegex>.*</pathRegex>\n"
        "    <metadataFrom>last</metadataFrom>\n"
        "    <sortFilesBySourceNames>station_id profile_id</sortFilesBySourceNames>\n"
        "    <addAttributes>\n"
        '        <att name="Conventions">CF-1.8, ACDD-1.3</att>\n'
        '        <att name="cdm_data_type">TimeSeriesProfile</att>\n'
        '        <att name="cdm_timeseries_variables">'
        "station_id, latitude, longitude</att>\n"
        '        <att name="cdm_profile_variables">'
        "profile_id, time</att>\n"
        '        <att name="featureType">timeSeriesProfile</att>\n'
        '        <att name="institution">NOAA SWFSC ERD</att>\n'
        '        <att name="license">Public Domain</att>\n'
        '        <att name="sourceUrl">(local files)</att>\n'
        '        <att name="summary">CTD profile observations from '
        "California Current System mooring stations</att>\n"
        '        <att name="title">California Current System CTD '
        "Profiles</att>\n"
        "    </addAttributes>\n"
        f"{dv_str}\n"
        "</dataset>"
    )

    with open(xml_path, "w") as f:
        f.write(xml_content)


def main():
    global_attrs, variables, data_rows = parse_nccsv(NCCSV_FILE)
    create_netcdf(NC_OUTPUT, global_attrs, variables, data_rows)
    create_datasets_xml(XML_OUTPUT)
    print(f"Created {NC_OUTPUT} ({sum(len(profiles) for profiles in [data_rows])} rows)")
    print(f"Created {XML_OUTPUT}")


if __name__ == "__main__":
    main()
