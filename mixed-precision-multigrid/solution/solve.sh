#!/bin/bash

# Install solution dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 matplotlib==3.9.3 -q

# Build the matrix generator
cd /app/matrix_gen
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1
make -j"$(nproc)" 2>&1

# Generate the sparse system files
./poisson_gen 63 /app

# Run the solver
cd /app
python3 /solution/solver.py
