#!/bin/bash

# Copy corrected C source and Python wrapper
cp /solution/if97_core_fixed.c /app/src/if97_core.c
cp /solution/wrapper_fixed.py /app/wrapper.py

# Build the corrected shared library
cd /app && make clean && make

# Compute Rankine cycle analysis
python3 /solution/compute_cycle.py
