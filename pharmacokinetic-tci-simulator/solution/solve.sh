#!/bin/bash

set -e

# Apply all fixes to the pharmacokinetic simulator
python3 /solution/fix_code.py

# Run the simulation to produce results.csv
Rscript /app/run_simulation.R
