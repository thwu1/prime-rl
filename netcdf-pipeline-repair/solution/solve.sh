#!/bin/bash

set -e
cd /app
mkdir -p work output

# ===================================================================
# Step 1: Fix obs_2018.nc — tas has _FillValue = NaN
#
# NaN fill values cause NCO averaging operators (ncra, ncwa) to treat
# ALL values as valid, since IEEE-754 NaN != NaN means no value ever
# matches the fill.  Replace NaN data values with a numeric fill value
# and update the _FillValue attribute.
# ===================================================================
ncap2 -O -s 'where(tas!=tas) tas=1.0e20f' data/obs_2018.nc work/f2018.nc
ncatted -O -a _FillValue,tas,o,f,1.0e20 work/f2018.nc

# ===================================================================
# Step 2: Fix obs_2019.nc — corrupt time record at index 6 (July)
#
# The time coordinate value is -999; data for that slice is already all
# fill.  Repair the time value so the record sorts correctly in the
# timeseries.  NCO averaging will automatically skip the fill data.
# ===================================================================
ncap2 -O -s 'time(6)=561.0' data/obs_2019.nc work/f2019.nc

# ===================================================================
# Step 3: Fix obs_2020.nc — non-standard coordinates & inconsistent fill
#
# - Dimensions are named y/x instead of lat/lon; coordinate variables
#   are nav_lat/nav_lon.  Rename for compatibility with the other files.
# - huss has _FillValue=-9999 but missing_value=1e30.  Delete the
#   inconsistent attribute and harmonize fill value with other files.
# ===================================================================
cp data/obs_2020.nc work/f2020.nc
ncrename -O -d y,lat -d x,lon -v nav_lat,lat -v nav_lon,lon work/f2020.nc
ncatted -O -a missing_value,huss,d,, work/f2020.nc
ncap2 -O -s 'where(huss==-9999.0f) huss=1.0e20f' work/f2020.nc work/f2020.nc
ncatted -O -a _FillValue,huss,o,f,1.0e20 work/f2020.nc

# ===================================================================
# Step 4: Concatenate into a single timeseries (36 months)
# ===================================================================
ncrcat -O work/f2018.nc work/f2019.nc work/f2020.nc output/timeseries.nc

# ===================================================================
# Step 5: Monthly climatology — average each calendar month across years
#
# Use ncra with stride-12 hyperslabbing: -d time,M,,12 selects every
# 12th record starting at position M, capturing the same calendar month
# across all three years.  NCO automatically skips fill values, so the
# corrupted July 2019 (all fill) contributes zero weight.
# ===================================================================
for m in $(seq 0 11); do
    mm=$(printf "%02d" "$m")
    ncra -O -d "time,$m,,12" output/timeseries.nc "work/clim_${mm}.nc"
done
ncrcat -O work/clim_*.nc output/climatology.nc

# ===================================================================
# Step 6: Derive vapor pressure deficit (VPD) via ncap2
#
# Tetens approximation for saturation vapor pressure:
#   es = 611.2 * exp(17.67 * T_C / (T_C + 243.5))   [Pa]
# Actual vapor pressure from specific humidity:
#   ea = q * P / (0.622 + 0.378 * q)                  [Pa]
# VPD = es - ea
# ===================================================================
ncap2 -O -s '
*tc=double(tas)-273.15;
*es=611.2*exp(17.67*tc/(tc+243.5));
*ea=double(huss)*101325.0/(0.622+0.378*double(huss));
vpd=float(es-ea);
vpd@long_name="Vapor Pressure Deficit";
vpd@units="Pa";
' output/climatology.nc output/climatology.nc

# ===================================================================
# Step 7: Latitude-weighted global mean
#
# Area weight = cos(latitude).  ncwa broadcasts the 1-D weight across
# the lon dimension and collapses both spatial dimensions.
# ===================================================================
ncap2 -O -s 'gw=float(cos(lat*3.14159265358979/180.0))' \
    output/climatology.nc work/clim_gw.nc
ncwa -O -w gw -a lat,lon work/clim_gw.nc output/global_means.nc
