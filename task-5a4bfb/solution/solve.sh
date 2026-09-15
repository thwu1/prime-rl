#!/bin/bash

set -e

# Copy solution module to /app
cp /solution/fast_mul.py /app/fast_mul.py

# Run the solution script to generate results.json
cd /app
python3 /solution/solve.py
