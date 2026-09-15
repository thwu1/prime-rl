#!/bin/bash

# Reference solution: replace source with adaptive solver, build, and run

cp /solution/solve_convdiff_fixed.cpp /app/solve_convdiff.cpp

cd /app
rm -rf build
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)

# Run produces output_*.txt and strategy.json
./solve_convdiff
