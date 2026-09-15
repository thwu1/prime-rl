#!/bin/bash

# Solution for hashmap-rehash-cycle task

set -e

# Step 1: Copy solution programs
cp /solution/simulate.c /app/simulate.c
cp /solution/detect_cycle.c /app/detect_cycle.c

# Step 2: Fix the hash table with thread synchronization
cp /solution/fixed_hashtable.h /app/hashtable.h
cp /solution/fixed_hashtable.c /app/hashtable.c

# Step 3: Build all targets
cd /app
make clean
make stress_test
make simulate
make detect_cycle

# Step 4: Run simulation and extract answer programmatically
echo "=== Running simulation ==="
SIM_OUTPUT=$(./simulate)
echo "$SIM_OUTPUT"

# Derive answer.txt from simulation output (not hardcoded)
grep -E '^CYCLE_BUCKET=' <<< "$SIM_OUTPUT" > /app/answer.txt
grep -E '^CYCLE_ENTRIES=' <<< "$SIM_OUTPUT" >> /app/answer.txt

echo ""
echo "=== Running cycle detection ==="
./detect_cycle

echo ""
echo "=== Running stress test ==="
./stress_test

echo ""
echo "=== Verifying answer.txt ==="
cat /app/answer.txt

echo ""
echo "=== Solution complete ==="
