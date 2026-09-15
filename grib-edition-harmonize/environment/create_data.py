#!/usr/bin/env python3
"""Create GRIB2 test data with embedded conformance defects for forensics task.

Each file contains a different subtle defect that requires expert-level
knowledge of GRIB format internals and meteorological conventions to diagnose.
"""

import os
import numpy as np
import eccodes

os.makedirs('/app/data', exist_ok=True)

# Grid: 36 longitudes x 18 latitudes (10-degree spacing)
Ni, Nj = 36, 18
lats = np.linspace(85.0, -85.0, Nj)
lons = np.linspace(0.0, 350.0, Ni)
lon_grid, lat_grid = np.meshgrid(lons, lats)
lat_r = np.radians(lat_grid.flatten())
lon_r = np.radians(lon_grid.flatten())


def write_msg(path, short_name, level, type_of_level, values,
              append=False, bits_per_value=16, j_scans_positively=0):
    """Write a single GRIB2 message to file."""
    mid = eccodes.codes_grib_new_from_samples('GRIB2')

    # Grid definition (Section 3)
    eccodes.codes_set(mid, 'gridType', 'regular_ll')
    eccodes.codes_set_long(mid, 'Ni', Ni)
    eccodes.codes_set_long(mid, 'Nj', Nj)
    eccodes.codes_set_double(mid, 'latitudeOfFirstGridPointInDegrees', 85.0)
    eccodes.codes_set_double(mid, 'latitudeOfLastGridPointInDegrees', -85.0)
    eccodes.codes_set_double(mid, 'longitudeOfFirstGridPointInDegrees', 0.0)
    eccodes.codes_set_double(mid, 'longitudeOfLastGridPointInDegrees', 350.0)
    eccodes.codes_set_double(mid, 'iDirectionIncrementInDegrees', 10.0)
    eccodes.codes_set_double(mid, 'jDirectionIncrementInDegrees', 10.0)
    eccodes.codes_set_long(mid, 'jScansPositively', j_scans_positively)

    # Product definition (Section 4) and identification
    eccodes.codes_set_long(mid, 'centre', 98)  # ECMWF
    eccodes.codes_set(mid, 'shortName', short_name)
    eccodes.codes_set(mid, 'typeOfLevel', type_of_level)
    eccodes.codes_set_long(mid, 'level', level)
    eccodes.codes_set_long(mid, 'dataDate', 20240115)
    eccodes.codes_set_long(mid, 'dataTime', 1200)

    # Data representation (Section 5)
    eccodes.codes_set_long(mid, 'bitsPerValue', bits_per_value)

    # Data values (Section 7)
    eccodes.codes_set_values(mid, values.tolist())

    mode = 'ab' if append else 'wb'
    with open(path, mode) as f:
        eccodes.codes_write(mid, f)
    eccodes.codes_release(mid)


# ================================================================
# DEFECT 1: Temperature — Insufficient packing precision
# bitsPerValue=4 gives only 16 discrete values over the data range,
# causing quantization errors of ~4 K per message — far below the
# sub-Kelvin precision required for operational NWP data.
# ================================================================
for i, lev in enumerate([500, 700, 850]):
    vals = 250.0 + 30.0 * np.cos(lat_r) - lev / 100.0 + 2.0 * np.sin(lon_r)
    write_msg('/app/data/forecast_temperature.grib', 't', lev,
              'isobaricInhPa', vals, append=(i > 0), bits_per_value=4)


# ================================================================
# DEFECT 2: Upper air field — Parameter identity mismatch
# Geopotential data (values ~54000 m^2/s^2) encoded with shortName='t'
# (temperature, paramId=130). The data values are clearly outside the
# physical domain of temperature (150-350 K) and match geopotential.
# ================================================================
vals_geo = 5500.0 * 9.81 + 100.0 * np.cos(lat_r) * 9.81
write_msg('/app/data/forecast_upper_air.grib', 't', 500,
          'isobaricInhPa', vals_geo)


# ================================================================
# DEFECT 3: Wind — Inconsistent scanning direction flags
# The grid runs from 85N to 85S (north-to-south), so jScansPositively
# should be 0. The 500 hPa messages are correct (0), but the 850 hPa
# messages have jScansPositively=1 (wrong), causing spatial inversion
# when decoded by compliant software.
# ================================================================
for i, lev in enumerate([500, 850]):
    u_vals = 10.0 * np.sin(2.0 * lon_r) * np.cos(lat_r) - lev / 200.0
    j_scan = 1 if lev == 850 else 0
    write_msg('/app/data/forecast_wind.grib', 'u', lev,
              'isobaricInhPa', u_vals, append=(i > 0),
              j_scans_positively=j_scan)

for i, lev in enumerate([500, 850]):
    v_vals = 5.0 * np.cos(lon_r) * np.sin(lat_r) + lev / 300.0
    j_scan = 1 if lev == 850 else 0
    write_msg('/app/data/forecast_wind.grib', 'v', lev,
              'isobaricInhPa', v_vals, append=True,
              j_scans_positively=j_scan)


# ================================================================
# DEFECT 4: Surface — Data in wrong units
# MSLP (shortName='msl') should be in Pascals (~101325 Pa) per WMO
# GRIB convention. Values are stored in hectopascals (~1013.25 hPa),
# which is the common meteorological convention but violates the
# GRIB encoding standard.
# ================================================================
mslp_pa = 101325.0 + 500.0 * np.cos(lat_r) - 200.0 * np.sin(lon_r)
mslp_hpa = mslp_pa / 100.0  # Wrong: stored as hPa instead of Pa
write_msg('/app/data/forecast_surface.grib', 'msl', 0,
          'meanSea', mslp_hpa)


# ================================================================
# DEFECT 5: Humidity — Duplicate vertical level metadata
# Two messages for relative humidity, both tagged as 700 hPa.
# One message actually contains 850 hPa data (higher mean RH,
# characteristic of lower troposphere). The second message's level
# should be 850 hPa.
# ================================================================
rh_700 = 50.0 + 20.0 * np.cos(lat_r) + 5.0 * np.sin(lon_r)
rh_850 = 70.0 + 15.0 * np.cos(lat_r) + 3.0 * np.sin(lon_r)
write_msg('/app/data/forecast_humidity.grib', 'r', 700,
          'isobaricInhPa', rh_700)
write_msg('/app/data/forecast_humidity.grib', 'r', 700,  # DEFECT: should be 850
          'isobaricInhPa', rh_850, append=True)


# ================================================================
# Generate QC rejection report (cryptic error codes only)
# ================================================================
qc_lines = [
    "============================================================",
    "INGEST QC REPORT  -  2024-01-15T12:00Z CYCLE",
    "Run: QC-2024011512-0847",
    "============================================================",
    "",
    "forecast_humidity.grib      REJECT  E-4003 (product definition)",
    "forecast_surface.grib       REJECT  E-4501 (data content)",
    "forecast_temperature.grib   REJECT  E-5001 (data representation)",
    "forecast_upper_air.grib     REJECT  E-4701 (cross-section coherence)",
    "forecast_wind.grib          REJECT  E-3001 (grid definition)",
    "",
    "Summary: 0/5 accepted",
    "============================================================",
]
with open('/app/qc_report.log', 'w') as f:
    f.write('\n'.join(qc_lines) + '\n')


# Print verification summary
print("GRIB test data with conformance defects created:")
for fname in sorted(os.listdir('/app/data')):
    fpath = os.path.join('/app/data', fname)
    count = 0
    with open(fpath, 'rb') as fh:
        while True:
            mid = eccodes.codes_grib_new_from_file(fh)
            if mid is None:
                break
            sn = eccodes.codes_get(mid, 'shortName')
            lev = eccodes.codes_get(mid, 'level')
            bpv = eccodes.codes_get(mid, 'bitsPerValue')
            jscan = eccodes.codes_get(mid, 'jScansPositively')
            tol = eccodes.codes_get(mid, 'typeOfLevel')
            vals = eccodes.codes_get_values(mid)
            count += 1
            print("  {} msg{}: sn={} lev={} tol={} bpv={} jScan={} range=[{:.2f},{:.2f}]".format(
                fname, count, sn, lev, tol, bpv, jscan, min(vals), max(vals)))
            eccodes.codes_release(mid)
