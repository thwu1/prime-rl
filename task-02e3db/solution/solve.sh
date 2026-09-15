#!/bin/bash


# Install solution dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Replace stub with complete implementation
cp /solution/pgo_solver_impl.py /app/pgo_solver.py

# Run the solver
cd /app
python3 pgo_solver.py
