#!/bin/bash

cd /app

# Run the solver to compute all results, endgame DB, and analysis
python3 /solution/solver.py

# Install the CLI solver
cp /solution/cli_solver.py /app/solve.py
chmod +x /app/solve.py
