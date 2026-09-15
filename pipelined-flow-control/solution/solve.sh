#!/bin/bash

# Solve: analyze arithmetic block latencies, generate compute.sv, verify.

pip3 install -q setuptools==75.8.0

cd /app

echo "=== Analyzing arithmetic block latencies ==="
python3 /solution/generate_solution.py

echo ""
echo "=== Running simulation ==="
./simulate
