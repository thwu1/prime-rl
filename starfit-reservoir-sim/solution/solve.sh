#!/bin/bash

# Phase 1: Fix NetCDF structural issues using NCO tools
# Rename misnamed variables to match the schema expected by io_utils.py
ncrename -v muskingum_K,reach_K_days \
         -v muskingum_x,reach_x \
         -v init_storage_mcm,initial_storage_MCM \
         /app/data/cascade.nc

# Extract the demand target value stored as a variable and add it as
# the global attribute that io_utils.py expects
DEMAND=$(python3 -c "
import netCDF4 as nc
ds = nc.Dataset('/app/data/cascade.nc')
print(float(ds.variables['downstream_demand_cms'][:]))
ds.close()
")
ncatted -a demand_target_cms,global,c,d,"$DEMAND" /app/data/cascade.nc

# Phase 2: Fix Python bugs and implement missing modules, then run
python3 /solution/solver.py
