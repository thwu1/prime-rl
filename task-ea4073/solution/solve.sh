#!/bin/bash

set -e
cd /app
mkdir -p results

# Force NetCDF classic output format to avoid HDF5 attribute issues
export CDO_PCTL_NBINS=101

# ---- Step 1: Conservative remapping to regular 10-degree grid ----
cdo -f nc remapcon,r36x18 data/tasmax_daily.nc results/tasmax_regrid.nc

# ---- Step 2: 90th percentile (5-day running window, ref 2001-2005) ----
# ydrunpctl requires three inputs: data, running-min, running-max
cdo -f nc selyear,2001/2005 results/tasmax_regrid.nc /tmp/tasmax_ref.nc
cdo -f nc ydrunmin,5 /tmp/tasmax_ref.nc /tmp/ydrun_min.nc
cdo -f nc ydrunmax,5 /tmp/tasmax_ref.nc /tmp/ydrun_max.nc
cdo -f nc ydrunpctl,90,5 /tmp/tasmax_ref.nc /tmp/ydrun_min.nc /tmp/ydrun_max.nc results/pctl90.nc

# ---- Step 3: Warm Spell Duration Index (eval 2006-2010) ----
# Process each evaluation year individually against the day-of-year
# percentile threshold to guarantee exactly 5 annual output timesteps
# and avoid time-axis matching issues between reference and eval periods.
for yr in 2006 2007 2008 2009 2010; do
    cdo -f nc selyear,$yr results/tasmax_regrid.nc /tmp/eval_${yr}.nc
    cdo -f nc eca_hwfi /tmp/eval_${yr}.nc results/pctl90.nc /tmp/wsdi_${yr}.nc
done
cdo -f nc mergetime /tmp/wsdi_2006.nc /tmp/wsdi_2007.nc /tmp/wsdi_2008.nc /tmp/wsdi_2009.nc /tmp/wsdi_2010.nc results/wsdi.nc

# ---- Step 4: Monthly climatology (ref 2001-2005) ----
cdo -f nc ymonmean -selyear,2001/2005 results/tasmax_regrid.nc results/ymon_clim.nc

# ---- Step 5: Monthly anomalies (full period minus climatology) ----
cdo -f nc ymonsub -monmean results/tasmax_regrid.nc results/ymon_clim.nc results/monthly_anomalies.nc

# ---- Step 6: Area-weighted global field mean of anomalies ----
cdo -f nc fldmean results/monthly_anomalies.nc results/fldmean_anomalies.nc

# Cleanup
rm -f /tmp/tasmax_ref.nc /tmp/ydrun_min.nc /tmp/ydrun_max.nc
rm -f /tmp/eval_*.nc /tmp/wsdi_*.nc
