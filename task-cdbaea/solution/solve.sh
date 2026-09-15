#!/bin/bash

# Install solver dependencies
pip3 install numpy==1.26.4 h5py==3.12.1 -q

# Deploy the solution solver
cp /solution/solver_solution.py /app/solver.py
