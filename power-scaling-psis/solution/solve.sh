#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Verify data files exist before running
if [ ! -f /app/data/samples.npz ]; then
    echo "ERROR: /app/data/samples.npz not found"
    ls -la /app/data/ 2>/dev/null || echo "/app/data/ does not exist"
    exit 1
fi

python3 /solution/psis_solver.py
