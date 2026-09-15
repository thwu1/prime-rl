#!/bin/bash

cp /solution/verifier.py /app/verifier.py
chmod +x /app/verifier.py

echo "=== Running verifier on all objects ==="
for f in /app/objects/*.o; do
    name=$(basename "$f" .o)
    result=$(python3 /app/verifier.py "$f")
    echo "$name: $result"
done
