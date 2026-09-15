#!/bin/bash

pip3 install tomli==2.0.1 -q 2>/dev/null || true

# Copy corrected files
cp /solution/pipeline.py /app/pipeline.py
cp /solution/thermal.f90 /app/thermal_lib/thermal.f90
cp /solution/Makefile /app/thermal_lib/Makefile

# Build the Fortran shared library
cd /app/thermal_lib && make clean && make

# Run the pipeline
cd /app
python3 /app/pipeline.py
