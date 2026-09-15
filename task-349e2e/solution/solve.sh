#!/bin/bash

# Deploy the solver
cp /solution/solver_impl.py /app/solver.py

# Run evaluation harness to produce benchmark report
cd /app
python3 evaluate.py
