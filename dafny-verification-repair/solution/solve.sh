#!/bin/bash

# Write the annotated Dafny programs with verification hints restored
python3 /solution/verified_programs.py

# Verify each program with Dafny
FAILED=0
for f in /app/sel_sort.dfy /app/insertion_sort.dfy /app/seq_max_sum.dfy; do
    echo "=== Verifying $f ==="
    dafny verify "$f" --verification-time-limit 120
    if [ $? -ne 0 ]; then
        echo "FAILED: $f"
        FAILED=1
    else
        echo "PASSED: $f"
    fi
    echo ""
done

if [ $FAILED -eq 1 ]; then
    echo "Some programs failed verification."
    exit 1
fi

echo "All programs verified successfully."
