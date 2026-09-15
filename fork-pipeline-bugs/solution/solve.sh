#!/bin/bash

python3 /solution/fix_pipeline.py

make -C /app clean && make -C /app

# Verify with different worker counts
for n in 1 3 4 7; do
    echo "=== Testing with $n workers ==="
    /app/pipeline /app/data/numbers.txt /app/output_${n}w.txt "$n"
    cat /app/output_${n}w.txt
    echo ""
done
