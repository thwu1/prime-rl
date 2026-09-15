#!/bin/bash

set -e

# Deploy the MaxSAT solver
cp /solution/maxsat_solver.py /app/maxsat_solver
chmod +x /app/maxsat_solver

# Deploy the fixed converter
cp /solution/wcnf2dimacs_fixed.py /app/tools/wcnf2dimacs_fixed.py

# Generate the bug report
python3 /solution/generate_report.py
