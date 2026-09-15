#!/bin/bash

# Install solution dependencies
pip3 install duckdb==1.1.0 -q

# Run the solver
python3 /solution/solver.py
