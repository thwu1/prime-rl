#!/bin/bash

cd /app

# Copy the full optimizer implementation to /app/optimizer.py
# (this is what an agent would do: replace the stub with a real implementation)
cp /solution/solve_optimizer.py /app/optimizer.py

# Run the optimizer to produce optimized plans in /app/optimized/
python3 /app/optimizer.py
