#!/bin/bash

set -e

# ── Step 1: Build Csmith from source ─────────────────────────────────────

echo "=== Building Csmith ==="
cd /app/csmith-src
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -5
make -j"$(nproc)" 2>&1 | tail -5

if [ ! -x /app/csmith-src/build/src/csmith ]; then
    echo "ERROR: Csmith build failed" >&2
    exit 1
fi
echo "Csmith binary: $(ls -la /app/csmith-src/build/src/csmith)"

# Quick sanity check
/app/csmith-src/build/src/csmith --seed 1 > /dev/null 2>&1
echo "Csmith sanity check passed."

# Set up a unified include directory for Csmith runtime headers
echo "=== Preparing Csmith include directory ==="
mkdir -p /app/csmith-include
cp /app/csmith-src/runtime/*.h /app/csmith-include/ 2>/dev/null || true
find /app/csmith-src/build -name "*.h" -path "*/runtime/*" -exec cp {} /app/csmith-include/ \; 2>/dev/null || true
echo "Csmith include directory contents:"
ls /app/csmith-include/

# ── Step 2: Create pipeline directory and install scripts ────────────────

echo "=== Setting up pipeline ==="
mkdir -p /app/pipeline

cp /solution/fuzz.sh /app/pipeline/fuzz.sh
cp /solution/interestingness.sh /app/pipeline/interestingness.sh
cp /solution/batch.sh /app/pipeline/batch.sh
chmod +x /app/pipeline/fuzz.sh /app/pipeline/interestingness.sh /app/pipeline/batch.sh

echo "Pipeline scripts installed."

# ── Step 3: Reduce example_large.c using delta debugging ────────────────

echo "=== Reducing example_large.c ==="

# Verify the file is interesting before reducing
if /app/pipeline/interestingness.sh /app/example_large.c; then
    echo "example_large.c confirmed interesting. Starting reduction..."
    python3 /solution/reducer.py \
        /app/pipeline/interestingness.sh \
        /app/example_large.c \
        /app/pipeline/example_reduced.c
    echo "Reduced file:"
    wc -l /app/pipeline/example_reduced.c
    cat /app/pipeline/example_reduced.c
else
    echo "ERROR: example_large.c not interesting, cannot reduce" >&2
    exit 1
fi

# ── Step 4: Run batch fuzzing ────────────────────────────────────────────

echo "=== Running batch fuzzing (seeds 1-20) ==="
cd /app
/app/pipeline/batch.sh 1 20

echo "=== Done ==="
echo "Pipeline components:"
ls -la /app/pipeline/
echo ""
echo "Report summary:"
jq '{total, pass, mismatch, crash, timeout, compile_error, ub}' /app/pipeline/report.json
