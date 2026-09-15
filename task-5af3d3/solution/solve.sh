#!/bin/bash

set -e

# Copy solution source to /app
cp /solution/analyzer_solution.cpp /app/analyzer.cpp

# Build
cd /app
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1
make -j"$(nproc)" 2>&1

# Run
cd /app
./build/analyzer

echo "Solution complete. Results written to /app/results.json"
