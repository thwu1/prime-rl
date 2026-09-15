#!/bin/bash

# Install solution dependencies
pip3 install numpy==1.26.4 scipy==1.13.1 -q

# Deploy the solver
cp /solution/amg_solver.py /app/amg_solver.py

# Verify on the isotropic 32x32 case
python3 /app/amg_solver.py \
    --matrix /app/data/iso_32.mtx \
    --tol 1e-8 \
    --output /app/results_verify.json

echo "Solution deployed and verified."
