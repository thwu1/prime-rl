#!/usr/bin/env bash

set -euo pipefail

cd /app

# Apply all fixes via the helper script
python3 /solution/fix_solver.py

# Build with cmake
rm -rf build
cmake -B build
cmake --build build

# Run the solver
./build/flood_solver

echo "Solution applied and solver executed successfully."
