#!/bin/bash

# Deploy the geometric multigrid implementation
cp /solution/multigrid_impl.py /app/multigrid.py

# Run the solver to compute results across all grid sizes
cd /app
python3 /app/run_solver.py
