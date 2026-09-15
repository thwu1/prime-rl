#!/bin/bash

# Copy fixed solver, Riemann solver, and study runner to /app/
cp /solution/euler_solver_fixed.py /app/euler_solver.py
cp /solution/exact_riemann_impl.py /app/exact_riemann.py
cp /solution/run_study_impl.py /app/run_study.py

# Run the full convergence study pipeline (gmsh -> solver -> gnuplot -> results)
cd /app && python3 /app/run_study.py
