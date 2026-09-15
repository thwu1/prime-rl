#!/bin/bash

set -e

mkdir -p /app/output

# =========================================================================
# Step 1: Fix NaN _FillValue in file A (Matlab/xarray NaN export issue).
#
# The _FillValue attribute is NaN, which causes NCO arithmetic operators
# (ncra, ncwa) to propagate NaN through all computations.
#
# Strategy: first change _FillValue attribute to a numeric sentinel,
# then replace the actual NaN data values with that sentinel.
# =========================================================================
ncatted -O \
    -a _FillValue,tas,o,d,-9999.0 \
    -a _FillValue,uas,o,d,-9999.0 \
    -a _FillValue,vas,o,d,-9999.0 \
    /app/data/model_200001-200008.nc /tmp/file_a_attr.nc

# NaN != NaN per IEEE 754, so where(x != x) selects exactly the NaN cells.
ncap2 -O -s '
  where(tas != tas) tas=-9999.0;
  where(uas != uas) uas=-9999.0;
  where(vas != vas) vas=-9999.0;
' /tmp/file_a_attr.nc /tmp/file_a_fixed.nc

# =========================================================================
# Step 2: Make time dimension unlimited in file B.
#
# ncrcat requires all input files to have a record (unlimited) dimension.
# File B has a fixed-size time dimension.
# =========================================================================
ncks -O --mk_rec_dmn time \
    /app/data/model_200009-200104.nc /tmp/file_b_fixed.nc

# =========================================================================
# Step 3: Rename non-standard dimension and coordinate names in file C.
#
# File C uses NEMO ocean model conventions: dims y/x and vars nav_lat/nav_lon.
# Must match files A & B which use lat/lon.
# =========================================================================
ncrename -O \
    -d y,lat -d x,lon \
    -v nav_lat,lat -v nav_lon,lon \
    /app/data/model_200105-200112.nc /tmp/file_c_fixed.nc

# Also clean up the stale 'coordinates' attribute that references old names
ncatted -O \
    -a coordinates,tas,d,, \
    -a coordinates,uas,d,, \
    -a coordinates,vas,d,, \
    /tmp/file_c_fixed.nc

# =========================================================================
# Step 4: Concatenate all three files into a single 24-month time series.
# =========================================================================
ncrcat -O \
    /tmp/file_a_fixed.nc \
    /tmp/file_b_fixed.nc \
    /tmp/file_c_fixed.nc \
    /tmp/concatenated.nc

# =========================================================================
# Step 5: Compute 12-month climatology.
#
# For each calendar month (0–11), average across both years using
# ncra with stride-based hyperslabbing: -d time,month,,12
# selects indices {month, month+12} and averages them.
# =========================================================================
for m in $(seq 0 11); do
    ncra -O -d time,"${m}",,12 \
        /tmp/concatenated.nc \
        /tmp/clim_$(printf "%02d" "$m").nc
done

ncrcat -O \
    /tmp/clim_00.nc /tmp/clim_01.nc /tmp/clim_02.nc /tmp/clim_03.nc \
    /tmp/clim_04.nc /tmp/clim_05.nc /tmp/clim_06.nc /tmp/clim_07.nc \
    /tmp/clim_08.nc /tmp/clim_09.nc /tmp/clim_10.nc /tmp/clim_11.nc \
    /tmp/climatology.nc

# =========================================================================
# Step 6: Derive wind speed from u/v wind components.
# =========================================================================
ncap2 -O -s '
  wind_speed = sqrt(uas*uas + vas*vas);
  wind_speed@long_name = "Wind Speed";
  wind_speed@units = "m s-1";
  wind_speed@standard_name = "wind_speed";
' /tmp/climatology.nc /app/output/climatology.nc

# =========================================================================
# Step 7: Compute area-weighted global mean of tas.
#
# Weight by cos(latitude) to account for grid cell area on a regular
# lat-lon grid. ncwa collapses lat and lon dimensions.
# =========================================================================
ncap2 -O -s '
  gw = cos(lat * 3.14159265358979 / 180.0);
  gw@long_name = "geographical weight";
' /app/output/climatology.nc /tmp/clim_weighted.nc

ncwa -O -a lat,lon -w gw -v tas \
    /tmp/clim_weighted.nc /app/output/global_mean_tas.nc

echo "Pipeline complete. Outputs:"
ncdump -h /app/output/climatology.nc | head -20
ncdump -h /app/output/global_mean_tas.nc | head -10
