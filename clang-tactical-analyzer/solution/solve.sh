#!/bin/bash

export PYTHONDONTWRITEBYTECODE=1

cp /solution/clang_analyzer.py /app/clang_analyzer.py
chmod +x /app/clang_analyzer.py

# Verify JSON output on all scenarios
for f in /app/scenarios/scenario_*.clang; do
    echo "=== Testing $(basename $f) ==="
    output=$(python3 /app/clang_analyzer.py "$f" 2>&1)
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "FAILED to run on $f (exit=$rc)"
        echo "$output"
        exit 1
    fi
    echo "$output" | python3 -m json.tool > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "FAILED: invalid JSON from $f"
        echo "$output" | head -20
        exit 1
    fi
    echo "OK"
done

# Run spot-check verification
python3 /solution/verify_solution.py
rc=$?
if [ $rc -ne 0 ]; then
    echo "FAILED spot-check verification"
    exit 1
fi

echo "All scenarios passed validation."
