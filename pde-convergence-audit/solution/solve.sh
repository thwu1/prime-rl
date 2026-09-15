#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Apply all fixes across the build system, C code, ctypes bindings, and Python solvers
python3 /solution/fix_all.py

# Build the C kernel shared library
cd /app && make clean && make

# Run the benchmark to produce results.json
python3 /app/run_benchmark.py
