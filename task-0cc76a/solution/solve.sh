#!/bin/bash

set -e

# Instrument parser.c with MAGMA canary calls and fix guards
python3 /solution/instrument.py

# Build with canaries enabled
cd /app
make clean
make CANARIES=1

# Create binary test inputs that trigger each bug
python3 /solution/create_tests.py

# Reset canary storage and run all test inputs
rm -f /tmp/magma_canary.raw
for f in /app/tests/test_img*.img; do
    ./imgparse "$f" 2>/dev/null || true
done

# Display canary results
echo "=== Canary Results (buggy) ==="
./monitor

# Rebuild with fixes and verify compilation
make clean
make CANARIES=1 FIXES=1
echo "=== Build with FIXES succeeded ==="
