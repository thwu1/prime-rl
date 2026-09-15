#!/bin/bash

# Deploy solver and convergence study implementations
cp /solution/solver_impl.py /app/solver.py
cp /solution/convergence_impl.py /app/convergence.py

# Run the solver to produce results.json
python3 /app/solver.py

# Run the convergence study to produce convergence.json
python3 /app/convergence.py
