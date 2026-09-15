#!/bin/bash

# Copy all solution files to /app
cp /solution/effects.py /app/effects.py
cp /solution/solver.py /app/solver.py
cp /solution/programs.py /app/programs.py

# Verify by running the solver (answers derived by computation, not hardcoded)
cd /app
python3 solver.py
