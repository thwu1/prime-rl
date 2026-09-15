#!/bin/bash

set -e

# Ensure bbpPairings is available
if [ ! -f /app/bbpPairings.exe ]; then
    if [ -d /app/bbpPairings-src ]; then
        echo "Building bbpPairings from source..."
        cd /app/bbpPairings-src && make -j$(nproc)
        cp bbpPairings.exe /app/bbpPairings.exe
    else
        echo "ERROR: bbpPairings source not found" >&2
        exit 1
    fi
fi

cd /app
python3 /solution/repair_and_complete.py
