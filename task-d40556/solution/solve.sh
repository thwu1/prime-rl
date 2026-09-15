#!/bin/bash

set -e

cd /app

# Run the scoring pipeline
python3 /solution/solve_pipeline.py

echo "Solution complete. Results in /app/results/"
ls -la /app/results/
