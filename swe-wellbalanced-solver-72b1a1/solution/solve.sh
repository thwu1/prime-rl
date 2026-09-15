#!/usr/bin/env bash

pip3 install numpy==2.1.3 h5py==3.12.1 -q

# Fix Makefile: add -fPIC, -lm, correct output name
cp /solution/Makefile_fixed /app/Makefile

# Fix C source: fmin -> fmax for s_R wave speed
cp /solution/flux_kernels_fixed.c /app/src/flux_kernels.c

# Compile the shared library
make -C /app clean
make -C /app

# Fix Python solver: ctypes types, wet/dry threshold,
# hydrostatic reconstruction, imposed_height BC, HDF5 dataset names
cp /solution/swe1d_solution.py /app/swe1d.py

# Verify all scenarios
cd /app
python3 -c "from swe1d import solve; r = solve('lake_at_rest'); print('lake_at_rest OK')"
python3 -c "from swe1d import solve; r = solve('dam_break_dry'); print('dam_break_dry OK')"
python3 -c "from swe1d import solve; r = solve('dam_break_wet'); print('dam_break_wet OK')"
python3 -c "from swe1d import solve; r = solve('subcritical_bump'); print('subcritical_bump OK')"
python3 -c "from swe1d import solve; r = solve('transcritical_shock'); print('transcritical_shock OK')"
python3 -c "from swe1d import parse_params; p = parse_params('/app/params/lake_at_rest.dat'); print('parse_params OK')"
python3 /app/swe1d.py lake_at_rest > /dev/null && echo "CLI OK"
