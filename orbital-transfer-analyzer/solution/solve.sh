#!/bin/bash

pip3 install numpy==2.1.3 -q

# Deploy corrected Python files
cp /solution/orbital_mechanics.py /app/lib/orbital.py
cp /solution/solver.py /app/run_missions.py

# Deploy corrected Makefile and jq filter
cp /solution/Makefile.fixed /app/Makefile
cp /solution/validate.fixed.jq /app/validate.jq

cd /app
make clean 2>/dev/null || true
make all
