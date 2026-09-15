#!/bin/bash


cd /app

# Apply all code fixes (Makefile, C code, config, integrator)
python3 /solution/apply_solution.py

# Build the native constraint library
make -C /app/native clean
make -C /app/native

# Run the simulation
python3 run_simulation.py
