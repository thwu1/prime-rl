#!/usr/bin/env python3
"""
Convert NCCSV ocean buoy data to CF-1.8 compliant NetCDF-4 with
indexed ragged array discrete sampling geometry, and generate an
ERDDAP datasets.xml configuration fragment.

Reference implementation for this task.
"""


import csv
import os
from collections import OrderedDict
from datetime import datetime, timezone
from io import StringIO

import netCDF4
import numpy as np

NCCSV_FILE = "/app/data/ocean_buoys.nccsv"
NC_OUTPUT = "/app/output/buoy_observations.nc"
XML_OUTPUT = "/app/output/dataset_config.xml"


def parse_nccsv(filepath):
    """Parse an NCCSV file into global_attrs, variables dict, and data rows."""
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
            var_name, attr_name, attr_value = parts[0], parts[1], parts[2]
            if var_name == "*GLOBAL*":
                global_attrs[attr_name] = attr_value
            else:
                if var_name not in variables:
                    variables[var_name] = {"data_type": "String", "attrs": OrderedDict()}
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


def iso_to_epoch(time_str):
    """Convert ISO 8601 time to seconds since 1970-01-01T00:00:00Z."""
    dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
    dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def create_netcdf(nc_path, global_attrs, variables, data_rows):
    """Create a CF-1.8 NetCDF-4 file with indexed ragged array DSG."""

    # Identify unique stations preserving order
    stations = OrderedDict()
    for row in data_rows:
        sid = row["station_id"]
        if sid not in stations:
            stations[sid] = {
                "lat": float(row["latitude"]),
                "lon": float(row["longitude"]),
            }

    station_names = list(stations.keys())
    n_stations = len(station_names)
    n_obs = len(data_rows)

    os.makedirs(os.path.dirname(nc_path), exist_ok=True)

    ds = netCDF4.Dataset(nc_path, "w", format="NETCDF4")

    # ── Dimensions ────────────────────────────────────────────────
    ds.createDimension("station", n_stations)
    ds.createDimension("obs", n_obs)

    # ── Global attributes ─────────────────────────────────────────
    ds.Conventions = "CF-1.8, COARDS, ACDD-1.3"
    ds.featureType = "timeSeries"
    ds.title = global_attrs.get("title", "")
    ds.summary = global_attrs.get("summary", "")
    ds.institution = global_attrs.get("institution", "")
    ds.creator_name = global_attrs.get("creator_name", "")
    ds.license = global_attrs.get("license", "")
    ds.cdm_data_type = "TimeSeries"
    ds.cdm_timeseries_variables = "station_name, latitude, longitude"
    ds.subsetVariables = "station_name"

    # ── Station-level variables ───────────────────────────────────

    # Station name (variable-length string, NetCDF-4 native)
    sn_var = ds.createVariable("station_name", str, ("station",))
    sn_var.long_name = variables.get("station_id", {}).get("attrs", {}).get(
        "long_name", "Station Identifier"
    )
    sn_var.cf_role = "timeseries_id"

    lat_var = ds.createVariable("latitude", "f8", ("station",))
    lat_var.standard_name = "latitude"
    lat_var.long_name = variables.get("latitude", {}).get("attrs", {}).get(
        "long_name", "Latitude"
    )
    lat_var.units = "degrees_north"
    lat_var.axis = "Y"

    lon_var = ds.createVariable("longitude", "f8", ("station",))
    lon_var.standard_name = "longitude"
    lon_var.long_name = variables.get("longitude", {}).get("attrs", {}).get(
        "long_name", "Longitude"
    )
    lon_var.units = "degrees_east"
    lon_var.axis = "X"

    # ── Index variable (indexed ragged array) ─────────────────────
    si_var = ds.createVariable("stationIndex", "i4", ("obs",))
    si_var.long_name = "index of station for this observation"
    si_var.instance_dimension = "station"

    # ── Time variable ─────────────────────────────────────────────
    time_var = ds.createVariable("time", "f8", ("obs",))
    time_var.standard_name = "time"
    time_var.long_name = "Time"
    time_var.units = "seconds since 1970-01-01T00:00:00Z"
    time_var.calendar = "gregorian"
    time_var.axis = "T"

    # ── Float measurement variables ───────────────────────────────
    fill_f4 = np.float32(netCDF4.default_fillvals["f4"])
    coord_str = "time latitude longitude station_name"

    float_vars_spec = [
        ("sea_surface_temp", "sea_surface_temperature", "Sea Surface Temperature", "degree_C"),
        ("salinity", "sea_surface_salinity", "Sea Surface Salinity", "PSU"),
        ("air_temperature", "air_temperature", "Air Temperature", "degree_C"),
        ("wind_speed", "wind_speed", "Wind Speed", "m s-1"),
    ]

    nc_float_vars = {}
    for nccsv_name, std_name, long_name, units in float_vars_spec:
        v = ds.createVariable(nccsv_name, "f4", ("obs",), fill_value=fill_f4)
        v.standard_name = std_name
        v.long_name = long_name
        v.units = units
        v.missing_value = fill_f4
        v.coordinates = coord_str
        nc_float_vars[nccsv_name] = v

    # ── Quality flag variable ─────────────────────────────────────
    fill_i4 = np.int32(netCDF4.default_fillvals["i4"])
    qf_var = ds.createVariable("quality_flag", "i4", ("obs",), fill_value=fill_i4)
    qf_var.long_name = "Quality Control Flag"
    qf_var.flag_values = np.array([1, 2, 3, 4], dtype=np.int32)
    qf_var.flag_meanings = "good suspect bad missing"
    qf_var.coordinates = coord_str

    # ── Write station data ────────────────────────────────────────
    for i, sname in enumerate(station_names):
        sn_var[i] = sname
        lat_var[i] = stations[sname]["lat"]
        lon_var[i] = stations[sname]["lon"]

    # ── Write observation data ────────────────────────────────────
    for obs_i, row in enumerate(data_rows):
        sid = row["station_id"]
        si_var[obs_i] = station_names.index(sid)
        time_var[obs_i] = iso_to_epoch(row["time"])

        for nccsv_name, nc_var in nc_float_vars.items():
            val = row.get(nccsv_name, "")
            if val == "" or val in ("NaN", "NaNf"):
                nc_var[obs_i] = fill_f4
            else:
                nc_var[obs_i] = float(val)

        qf_val = row.get("quality_flag", "")
        if qf_val == "":
            qf_var[obs_i] = fill_i4
        else:
            qf_var[obs_i] = int(qf_val)

    ds.close()


def create_datasets_xml(xml_path, variables):
    """Generate ERDDAP datasets.xml fragment for EDDTableFromNcFiles."""
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)

    data_var_blocks = []
    var_specs = [
        ("station_name", "String", "Identifier", "timeseries_id", None),
        ("time", "double", "Time", None, "time"),
        ("latitude", "double", "Location", None, "latitude"),
        ("longitude", "double", "Location", None, "longitude"),
        ("sea_surface_temp", "float", "Temperature", None, "sea_surface_temperature"),
        ("salinity", "float", "Salinity", None, "sea_surface_salinity"),
        ("air_temperature", "float", "Temperature", None, "air_temperature"),
        ("wind_speed", "float", "Wind", None, "wind_speed"),
        ("quality_flag", "int", "Quality", None, None),
    ]

    for src_name, dtype, ioos_cat, cf_role, std_name in var_specs:
        attrs = []
        attrs.append(f'            <att name="ioos_category">{ioos_cat}</att>')
        if cf_role:
            attrs.append(f'            <att name="cf_role">{cf_role}</att>')
        if std_name:
            attrs.append(f'            <att name="standard_name">{std_name}</att>')
        attrs_str = "\n".join(attrs)
        block = f"""    <dataVariable>
        <sourceName>{src_name}</sourceName>
        <dataType>{dtype}</dataType>
        <addAttributes>
{attrs_str}
        </addAttributes>
    </dataVariable>"""
        data_var_blocks.append(block)

    dv_str = "\n".join(data_var_blocks)

    xml_content = f"""<dataset type="EDDTableFromNcFiles" datasetID="pacific_buoy_obs" active="true">
    <reloadEveryNMinutes>10080</reloadEveryNMinutes>
    <fileDir>/data/netcdf/</fileDir>
    <fileNameRegex>buoy_observations\\.nc</fileNameRegex>
    <recursive>false</recursive>
    <pathRegex>.*</pathRegex>
    <metadataFrom>last</metadataFrom>
    <sortedColumnSourceName>time</sortedColumnSourceName>
    <sortFilesBySourceNames>station_name time</sortFilesBySourceNames>
    <addAttributes>
        <att name="Conventions">CF-1.8, COARDS, ACDD-1.3</att>
        <att name="cdm_data_type">TimeSeries</att>
        <att name="cdm_timeseries_variables">station_name, latitude, longitude</att>
        <att name="featureType">timeSeries</att>
        <att name="infoUrl">https://www.ndbc.noaa.gov/</att>
        <att name="institution">NOAA NDBC</att>
        <att name="keywords">buoy, ocean, temperature, salinity, wind, Pacific Coast</att>
        <att name="license">Public Domain</att>
        <att name="sourceUrl">(local files)</att>
        <att name="subsetVariables">station_name</att>
        <att name="summary">Hourly observations from NDBC buoys along the US Pacific Coast. Includes sea surface temperature, salinity, air temperature, and wind measurements.</att>
        <att name="title">Pacific Coast Ocean Buoy Observations</att>
    </addAttributes>
{dv_str}
</dataset>"""

    with open(xml_path, "w") as f:
        f.write(xml_content)


def main():
    global_attrs, variables, data_rows = parse_nccsv(NCCSV_FILE)
    create_netcdf(NC_OUTPUT, global_attrs, variables, data_rows)
    create_datasets_xml(XML_OUTPUT, variables)
    print(f"Created {NC_OUTPUT} ({len(data_rows)} observations)")
    print(f"Created {XML_OUTPUT}")


if __name__ == "__main__":
    main()
