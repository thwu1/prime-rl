#!/bin/bash

# Install the correct MESI protocol implementation and build the simulator.
mkdir -p /app/src
cp /solution/protocol.c /app/src/protocol.c
cd /app
make clean && make

# Verify against all provided traces
PASS=0
FAIL=0
for trace in /app/traces/*.trace; do
    name=$(basename "$trace")
    output=$(./mesi_sim "$trace" 2>&1)
    rc=$?
    if [ $rc -eq 0 ]; then
        PASS=$((PASS + 1))
        echo "PASS: $name"
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $name (exit code $rc)"
        echo "$output"
    fi
done
echo ""
echo "Results: $PASS passed, $FAIL failed"
