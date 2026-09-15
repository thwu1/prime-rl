#!/bin/bash

# Deploy the simulator implementation
cp /solution/simulator_impl.py /app/simulator.py

# Verify against each sample trace
for trace in /app/traces/*.jsonl; do
    name=$(basename "$trace" .jsonl)
    expected="/app/expected/${name}.json"
    actual=$(python3 /app/simulator.py --config /app/config.json --trace "$trace")
    if [ -f "$expected" ]; then
        expected_content=$(cat "$expected")
        if [ "$actual" != "$expected_content" ]; then
            echo "MISMATCH on $name" >&2
            echo "Expected: $expected_content" >&2
            echo "Got:      $actual" >&2
            exit 1
        fi
    fi
done

echo "Simulator verified against all sample traces."
