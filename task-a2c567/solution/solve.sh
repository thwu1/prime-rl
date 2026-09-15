#!/bin/bash

# Install solution dependencies
pip3 install netCDF4==1.7.2 numpy==2.1.3 -q

# Copy solution cmorizer to /app and run it
cp /solution/cmorizer_solution.py /app/cmorize.py
python3 /app/cmorize.py
