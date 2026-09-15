#!/bin/bash
# Climate variability analysis pipeline
# Chains CDO preprocessing, NCO variable computation, and Python analysis.

DATAFILE=/app/data/climate_output.nc
WORKDIR=/tmp/pipeline_work
mkdir -p $WORKDIR

echo "=== Step 1: Preparing temperature field ==="

# Replace missing/NaN values with zero for clean matrix operations
cdo -s setmisstoc,0 -selvar,tas $DATAFILE $WORKDIR/tas_clean.nc

# Compute latitude-dependent area weights for spatial covariance weighting
ncap2 -O -s 'area_weight=sin(lat*3.14159265358979/180.0)' \
  $DATAFILE $WORKDIR/weights.nc

echo "=== Step 2: EOF decomposition ==="
python3 /app/pipeline/eof_analysis.py $WORKDIR/tas_clean.nc $WORKDIR/weights.nc

echo "=== Step 3: Preparing Gregory regression data ==="

# Select time window and extract 1-D regression variables
ncks -O -d time,0,149 -v toa_imbalance,gmst_anomaly $DATAFILE $WORKDIR/gregory_data.nc

echo "=== Step 4: Gregory regression ==="
python3 /app/pipeline/gregory.py $WORKDIR/gregory_data.nc

echo "=== Step 5: Combining results ==="
python3 /app/pipeline/combine_results.py

echo "Pipeline complete."
