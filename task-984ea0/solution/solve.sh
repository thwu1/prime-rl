#!/bin/bash

set -e

# Install solution dependencies
pip3 install numpy==2.1.3 h5py==3.12.1 -q

# 1. Write the complete C kernel implementation
cp /solution/kernels_complete.c /app/src/kernels.c

# 2. Compile the C shared library
cd /app/src && make clean && make
echo "=== C library compiled ==="
ls -la /app/src/libkernels.so

# 3. Write the complete Python solver
cp /solution/solver_complete.py /app/solver.py

# 4. Run evaluation to verify accuracy
cd /app
python3 /app/evaluate.py
