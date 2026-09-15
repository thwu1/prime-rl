#!/bin/bash

set -e

pip3 install numpy==2.1.3 -q

# Apply the optimized implementation
cp /solution/edge_detect_optimized.c /app/edge_detect.c

# Rebuild optimized binary
cd /app
make clean
make edge_detect

# Build baseline reference for comparison
make edge_detect_ref

# Run both and verify correctness
./edge_detect_ref input.bin /tmp/ref_out.bin 8
./edge_detect input.bin /tmp/opt_out.bin 8

python3 /solution/verify.py /tmp/ref_out.bin /tmp/opt_out.bin

echo "Solution applied and verified successfully."
