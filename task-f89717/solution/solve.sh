#!/usr/bin/env bash

set -e

# Ensure buggy source files are in /app (restore from staging if needed)
if [ ! -f /app/quadrature.py ]; then
    cp /opt/task/quadrature.py /app/quadrature.py
fi
if [ ! -f /app/compute.py ]; then
    cp /opt/task/compute.py /app/compute.py
fi

# Fix all bugs in the quadrature library
python3 /solution/fix_quadrature.py

# Compute benchmark integrals with the corrected library
python3 /app/compute.py
