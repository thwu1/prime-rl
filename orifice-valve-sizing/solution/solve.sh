#!/bin/bash

# Fix 1: Makefile — add -lm for math library linking
cp /solution/Makefile_fixed /app/Makefile

# Fix 2-3: C source — fix M2' denominator and expansibility exponent
cp /solution/flowcore_fixed.c /app/src/flowcore.c

# Build the shared library
cd /app && make clean && make

# Fix 4-6: Python module — fix tap mapping, liquid valve FL/FLP, gas valve Y clamp
cp /solution/flowcal_fixed.py /app/flowcal.py

# Complete the calibration pipeline with valve processors
cp /solution/run_calibration_complete.py /app/run_calibration.py

# Run the calibration pipeline to produce results.json
python3 /app/run_calibration.py
