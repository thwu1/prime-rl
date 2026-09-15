#!/bin/bash


cd /app

# Verify task files are present
if [ ! -f "/app/affinity_engine/placement.py" ]; then
    echo "ERROR: Task source files not found at /app/affinity_engine/"
    echo "Contents of /app/:"
    ls -la /app/
    exit 1
fi

python3 /solution/fix_engine.py
