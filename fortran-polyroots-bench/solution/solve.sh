#!/bin/bash

set -eo pipefail

# === Step 1: Compile polyroots-fortran library at real64 ===
mkdir -p /tmp/build_r64
cd /tmp/build_r64

# Multi-pass compilation to resolve Fortran module dependencies
SRC_FILES=$(find /opt/polyroots-fortran/src \( -name '*.F90' -o -name '*.f90' \) -type f | sort)
for pass in 1 2 3 4; do
    for f in $SRC_FILES; do
        gfortran -c -O2 -J/tmp/build_r64 "$f" 2>/dev/null || true
    done
done
ar rcs libpolyroots.a *.o
echo "=== polyroots-fortran built at real64 ==="

# === Step 2: Compile and run benchmark at real64 ===
gfortran -O2 -I/tmp/build_r64 \
    /solution/benchmark.F90 \
    -L/tmp/build_r64 -lpolyroots -llapack -lblas \
    -o /tmp/bench_r64
/tmp/bench_r64
echo "=== real64 benchmark complete ==="

# === Step 3: Compile polyroots-fortran library at real128 ===
mkdir -p /tmp/build_r128
cd /tmp/build_r128

for pass in 1 2 3 4; do
    for f in $SRC_FILES; do
        gfortran -c -O2 -DREAL128 -J/tmp/build_r128 "$f" 2>/dev/null || true
    done
done
ar rcs libpolyroots.a *.o
echo "=== polyroots-fortran built at real128 ==="

# === Step 4: Compile and run benchmark at real128 ===
gfortran -O2 -DREAL128 -I/tmp/build_r128 \
    /solution/benchmark.F90 \
    -L/tmp/build_r128 -lpolyroots -llapack -lblas \
    -o /tmp/bench_r128
/tmp/bench_r128
echo "=== real128 benchmark complete ==="

# === Step 5: Parse output and generate /app/results.json ===
python3 /solution/parse_results.py
echo "=== results.json generated ==="
