#!/bin/bash

set -e

mkdir -p /app/physinfer
cp /solution/analyzer.py /app/physinfer/analyze.py

for f in /app/data/*.h5; do
    echo "Analyzing: $f"
    python3 /app/physinfer/analyze.py "$f"
    echo "---"
done

echo "Solution deployed and verified."
