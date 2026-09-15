#!/bin/bash

python3 /solution/gen_engine.py

cd /app
make run

echo "=== Simulation outputs ==="
for f in response_a.txt response_b.txt response_atomic.txt response_switch.txt latency.txt; do
    echo "--- $f ---"
    cat "/app/$f"
done
