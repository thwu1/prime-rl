#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/dgsem_solver.py /app/dgsem_solver.py
cp /solution/verify_sbp.m /app/verify_sbp.m

cd /app

echo "=== Running DGSEM solver ==="
python3 dgsem_solver.py

echo ""
echo "=== Running Octave SBP verification ==="
octave --no-gui /app/verify_sbp.m

echo ""
echo "All done."
