#!/bin/bash

# Copy optimizer into place
cp /solution/optimizer.py /app/optimizer.py

# Run optimizer on all test programs
mkdir -p /tmp/optimized
for f in /app/programs/*.obj; do
    base=$(basename "$f" .obj)
    echo "Optimizing $base..."
    python3 /app/optimizer.py "$f" "/tmp/optimized/${base}.obj"
done
