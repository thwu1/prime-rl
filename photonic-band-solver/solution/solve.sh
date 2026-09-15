#!/bin/bash

set -e

# Install numerical dependencies
pip3 install numpy==1.26.4 scipy==1.13.1 -q

# Deploy solver scripts to /app
cp /solution/solve_bands.py /app/solve_bands.py
cp /solution/optimize_gap.py /app/optimize_gap.py
cp /solution/convergence.py /app/convergence.py
chmod +x /app/solve_bands.py /app/optimize_gap.py /app/convergence.py
