#!/usr/bin/env bash

set -eu

# Ensure library modules are available in /app
for f in galois.py reed_solomon.py cluster.py storage.py; do
    if [ ! -f "/app/$f" ] && [ -f "/opt/ec_libs/$f" ]; then
        cp "/opt/ec_libs/$f" "/app/$f"
    fi
done

# Part 1: Recover data from binary crash dump
python3 /solution/solve_forensics.py

# Part 2: Install the transition engine implementation
cp /solution/transition_engine_impl.py /app/transition_engine.py

echo "Solution installed."
