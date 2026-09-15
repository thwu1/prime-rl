#!/bin/bash

# Copy optimized DGEMM implementation over the starter code
cp /solution/optimized_dgemm.c /app/dgemm-blocked.c

# Build the project
mkdir -p /app/build
cd /app/build
cmake -DCMAKE_BUILD_TYPE=Release ..
make -j2

# Verify correctness and display performance
echo "=== Optimized DGEMM benchmark ==="
./benchmark-blocked
echo ""
echo "=== Naive reference benchmark ==="
./benchmark-naive
