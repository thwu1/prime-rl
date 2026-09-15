#!/bin/bash

# Install solution dependencies
pip3 install eccodes==1.7.1 numpy==1.26.4 -q

cd /app

# Run the diagnostic and repair solver
python3 /solution/solver.py
