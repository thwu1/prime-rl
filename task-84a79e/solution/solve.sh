#!/usr/bin/env bash

# Copy the optimizer implementation to /app
cp /solution/optimizer_impl.py /app/optimizer.py
chmod +x /app/optimizer.py

# Verify on all programs
for i in 1 2 3 4 5; do
    echo "=== Optimizing prog${i} ==="
    python3 /app/optimizer.py /app/programs/prog${i}.ir > /tmp/opt_prog${i}.ir
    echo "--- Interpreter output (optimized) ---"
    python3 /app/interpreter.py /tmp/opt_prog${i}.ir
    echo "--- Expected ---"
    cat /app/expected_outputs/prog${i}.out
    echo ""
done
