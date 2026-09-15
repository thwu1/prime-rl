#!/bin/bash

# Install solution-only dependencies
pip3 install PyYAML==6.0.2 numpy==1.26.4 netCDF4==1.6.5 -q

# Run the CMORizer solution
python3 /solution/cmorizer.py
