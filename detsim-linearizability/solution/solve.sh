#!/bin/bash

set -e

cd /app

# Run the solution: writes pipeline.py, results.json, and fault configs
python3 /solution/solve_impl.py

echo "Solution complete."
