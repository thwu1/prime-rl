#!/bin/bash

set -e

# Install dependencies (phreeqpython bundles IPhreeqc; no system phreeqc needed)
pip3 install phreeqpython==1.5.7 scipy==1.14.1 numpy==2.1.3 -q

# Copy solution and run
cp /solution/solve.py /app/geochem_pipeline.py
python3 /app/geochem_pipeline.py
