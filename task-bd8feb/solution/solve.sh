#!/bin/bash

set -e

# Replace the incomplete implementation with the complete one
cp /solution/main_fixed.rs /app/src/main.rs

# Build
cd /app
cargo build --release 2>&1

# Verify against sample tests
echo "=== Verifying sample1 ==="
./target/release/forest_query < data/sample1.in > /tmp/out1.txt
diff /tmp/out1.txt data/sample1.out && echo "PASS" || { echo "FAIL"; exit 1; }

echo "=== Verifying sample2 ==="
./target/release/forest_query < data/sample2.in > /tmp/out2.txt
diff /tmp/out2.txt data/sample2.out && echo "PASS" || { echo "FAIL"; exit 1; }
