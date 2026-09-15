#!/usr/bin/env python3
"""Generate a deliberately non-compliant oceanographic netCDF dataset.

This script creates a realistic ocean station time-series file with numerous
embedded CF and ACDD compliance violations that must be programmatically repaired.
"""
import numpy as np
import netCDF4 as nc

output_path = "/app/ocean_station.nc"
ds = nc.Dataset(output_path, "w", format="NETCDF4")

# ============================================================
# DIMENSIONS
# ============================================================
ds.createDimension("time", None)  # unlimited
ds.createDimension("depth", 20)

# ============================================================
# GLOBAL ATTRIBUTES - deliberately incomplete / malformed
# ============================================================
ds.featureType = "timeSeries"
ds.history = ""  # empty string violates ACDD
ds.processing_level = "L1"
# MISSING: Conventions, title, summary, source, institution, creator_name,
#   creator_email, creator_url, project, keywords, license,
#   standard_name_vocabulary, id, naming_authority, date_created,
#   geospatial_lat_min/max, geospatial_lon_min/max,
#   geospatial_vertical_min/max, time_coverage_start/end, comment

# ============================================================
# TIME VARIABLE - wrong units format, missing attributes, dangling bounds
# ============================================================
time_var = ds.createVariable("time", "f8", ("time",))
time_var.units = "secs since 2023-1-1"  # "secs" not standard CF; date format wrong
time_var.bounds = "time_bnds"  # DANGLING: no time_bnds variable exists
# MISSING: calendar, axis, long_name, standard_name

np.random.seed(42)
time_data = np.arange(0, 365 * 86400, 86400, dtype=np.float64)
time_var[:] = time_data

# ============================================================
# DEPTH VARIABLE - missing positive, axis, long_name
# ============================================================
depth_var = ds.createVariable("depth", "f4", ("depth",))
depth_var.units = "m"
depth_var.standard_name = "depth"
# MISSING: positive (required for vertical coords), axis, long_name

depth_data = np.array(
    [5, 10, 15, 20, 30, 40, 50, 75, 100, 125,
     150, 200, 250, 300, 400, 500, 600, 800, 1000, 1500],
    dtype=np.float32,
)
depth_var[:] = depth_data

# ============================================================
# LATITUDE - missing units, axis
# ============================================================
lat_var = ds.createVariable("latitude", "f8", ())
lat_var.standard_name = "latitude"
# MISSING: units (must be degrees_north), axis, long_name
lat_var[:] = 42.3501

# ============================================================
# LONGITUDE - missing units, axis
# ============================================================
lon_var = ds.createVariable("longitude", "f8", ())
lon_var.standard_name = "longitude"
# MISSING: units (must be degrees_east), axis, long_name
lon_var[:] = -70.8833

# ============================================================
# TEMPERATURE - invalid standard_name, non-canonical units
# ============================================================
temp_var = ds.createVariable(
    "temperature", "f4", ("time", "depth"), fill_value=np.float32(-9999.0)
)
temp_var.standard_name = "temp"       # INVALID - not in CF standard name table
temp_var.units = "Celsius"            # non-canonical; should be degree_Celsius
# MISSING: long_name, coordinates, cell_methods

temp_data = np.random.uniform(2, 22, (365, 20)).astype(np.float32)
for d in range(20):
    temp_data[:, d] -= d * 0.8
temp_var[:] = temp_data

# ============================================================
# SALINITY - missing units entirely
# ============================================================
sal_var = ds.createVariable(
    "salinity", "f4", ("time", "depth"), fill_value=np.float32(-9999.0)
)
sal_var.standard_name = "sea_water_practical_salinity"
# MISSING: units (should be 1e-3 or 0.001), long_name, coordinates, cell_methods

sal_data = np.random.uniform(33, 36, (365, 20)).astype(np.float32)
sal_var[:] = sal_data

# ============================================================
# PRESSURE - valid_range clips actual data, missing long_name/coordinates
# ============================================================
pres_var = ds.createVariable(
    "pressure", "f4", ("time", "depth"), fill_value=np.float32(-9999.0)
)
pres_var.standard_name = "sea_water_pressure"
pres_var.units = "dbar"
pres_var.valid_range = np.array([0, 200], dtype=np.float32)  # WRONG: data goes up to ~1515
# MISSING: long_name, coordinates, cell_methods

pres_data = np.zeros((365, 20), dtype=np.float32)
for d in range(20):
    pres_data[:, d] = depth_data[d] * 1.01
pres_var[:] = pres_data

# ============================================================
# CURRENT SPEED - wrong cell_methods syntax
# ============================================================
spd_var = ds.createVariable(
    "current_speed", "f4", ("time", "depth"), fill_value=np.float32(-9999.0)
)
spd_var.standard_name = "sea_water_speed"
spd_var.units = "m s-1"
spd_var.cell_methods = "time average"  # WRONG: missing colon separator
# MISSING: long_name, coordinates

spd_data = np.random.uniform(0, 1.5, (365, 20)).astype(np.float32)
spd_var[:] = spd_data

# ============================================================
# CURRENT DIRECTION - missing long_name, coordinates
# ============================================================
dir_var = ds.createVariable(
    "current_direction", "f4", ("time", "depth"), fill_value=np.float32(-9999.0)
)
dir_var.standard_name = "direction_of_sea_water_velocity"
dir_var.units = "degree"
# MISSING: long_name, coordinates, cell_methods

dir_data = np.random.uniform(0, 360, (365, 20)).astype(np.float32)
dir_var[:] = dir_data

# ============================================================
# DISSOLVED OXYGEN - completely wrong standard_name + units mismatch
# ============================================================
do_var = ds.createVariable(
    "dissolved_oxygen", "f4", ("time", "depth"), fill_value=np.float32(-9999.0)
)
do_var.standard_name = "DO_concentration"  # INVALID standard name
do_var.units = "ml/l"  # non-CF canonical unit for dissolved O2
# MISSING: long_name, coordinates, cell_methods

do_data = np.random.uniform(2, 8, (365, 20)).astype(np.float32)
do_var[:] = do_data

# ============================================================
# TEMPERATURE QC - flag_values without flag_meanings
# ============================================================
qc_var = ds.createVariable("temperature_qc", "i1", ("time", "depth"))
qc_var.long_name = "Quality flag for temperature"
qc_var.flag_values = np.array([0, 1, 2, 3, 4, 9], dtype=np.int8)
# MISSING: flag_meanings (required when flag_values is present)

qc_data = np.random.choice(
    [0, 1, 2, 3, 4, 9], (365, 20),
    p=[0.7, 0.1, 0.05, 0.05, 0.05, 0.05],
).astype(np.int8)
qc_var[:] = qc_data

# ============================================================
# CHLOROPHYLL - units incompatible with standard_name
# ============================================================
chl_var = ds.createVariable(
    "chlorophyll", "f4", ("time", "depth"), fill_value=np.float32(-9999.0)
)
chl_var.standard_name = "mass_concentration_of_chlorophyll_a_in_sea_water"
chl_var.units = "ug/l"  # should be kg m-3 for the given standard_name
# MISSING: long_name, coordinates, cell_methods

chl_data = np.random.uniform(0.01, 15.0, (365, 20)).astype(np.float32)
chl_var[:] = chl_data

# ============================================================
# TURBIDITY - ancillary_variables pointing to nonexistent variable
# ============================================================
turb_var = ds.createVariable(
    "turbidity", "f4", ("time", "depth"), fill_value=np.float32(-9999.0)
)
turb_var.standard_name = "sea_water_turbidity"
turb_var.units = "1"
turb_var.ancillary_variables = "turbidity_qc"  # this variable doesn't exist!
# MISSING: long_name, coordinates

turb_data = np.random.uniform(0, 50, (365, 20)).astype(np.float32)
turb_var[:] = turb_data

ds.close()
print(f"Created non-compliant dataset at {output_path}")
