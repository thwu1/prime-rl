#!/bin/bash

set -e

# Install runtime dependency
pip3 install numpy==2.1.3 -q

cd /app

# Run the finite volume solver
python3 /solution/euler_solver.py
