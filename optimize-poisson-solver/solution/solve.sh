#!/bin/bash

set -e

cd /app

# === Profile the naive solver with cachegrind (reduced grid N=30) ===
sed 's/#define N 100/#define N 30/' /app/poisson3d.c > /tmp/poisson3d_small.c
gcc -g -O2 -std=c99 -o /tmp/poisson3d_small /tmp/poisson3d_small.c -lm
valgrind --tool=cachegrind /tmp/poisson3d_small 2> /tmp/cg_output.txt || true
python3 /solution/parse_cachegrind.py /tmp/cg_output.txt /app/profile_report.txt

# === Install solution files ===
cp /solution/CMakeLists.txt /app/CMakeLists.txt
cp /solution/fast_poisson.c /app/fast_poisson.c

# === Build with CMake (out-of-source) ===
rm -rf /app/build
mkdir -p /app/build
cd /app/build
cmake ..
make

# === Run the optimized solver ===
rm -f /app/results.txt /app/solution.bin
./fast_poisson
