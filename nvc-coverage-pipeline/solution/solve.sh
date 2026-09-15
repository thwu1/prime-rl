#!/bin/bash

set -e

# Run the solution helper to fix bugs, write testbench, and create pipeline
python3 /solution/solve_helper.py all

# Execute the coverage pipeline
bash /app/run_coverage.sh
