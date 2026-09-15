#!/bin/bash

set -e

# Copy the optimized implementation into place
cp /solution/optimized.c /app/src/optimized.c

# Build the project
cd /app
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j

# Verify correctness
/app/build/test_runner
