#!/bin/bash

set -e

# Copy the optimized implementation into place
cp /solution/correlate_optimized.cpp /app/correlate.cpp

# Build
cd /app && make clean && make

# Quick sanity check
echo "=== Sanity check: n=100 d=50 ==="
/app/benchmark 100 50 /tmp/sanity.bin

echo "=== Benchmark: n=1500 d=500 ==="
/app/benchmark 1500 500 /tmp/perf.bin

echo "Solution deployed and benchmarked."
