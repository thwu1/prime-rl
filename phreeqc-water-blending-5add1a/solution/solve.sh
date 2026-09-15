#!/bin/bash

set -uo pipefail

echo "=== Building PHREEQC3 from source ==="
cd /tmp

if [ ! -d "/tmp/phreeqc3-master" ]; then
    wget -q https://github.com/phreeqc-dev/phreeqc3/archive/refs/heads/master.tar.gz -O phreeqc3.tar.gz
    tar xzf phreeqc3.tar.gz --no-same-owner --no-same-permissions 2>/dev/null || true
    if [ ! -d "/tmp/phreeqc3-master" ]; then
        echo "ERROR: Failed to extract phreeqc3 source"
        exit 1
    fi
    rm -f phreeqc3.tar.gz
fi

cd phreeqc3-master
mkdir -p _build && cd _build
cmake .. -DCMAKE_BUILD_TYPE=Release > /dev/null 2>&1
make -j$(nproc) 2>&1 | tail -3

PHREEQC_BIN=$(find /tmp/phreeqc3-master/_build -name "phreeqc" -type f -executable 2>/dev/null | head -1)
PHREEQC_DB=$(find /tmp/phreeqc3-master -name "phreeqc.dat" -path "*/database/*" 2>/dev/null | head -1)

if [ -z "$PHREEQC_BIN" ] || [ -z "$PHREEQC_DB" ]; then
    echo "ERROR: Could not find PHREEQC binary or database"
    find /tmp/phreeqc3-master/_build -type f -executable 2>/dev/null | head -10
    exit 1
fi

echo "PHREEQC binary: $PHREEQC_BIN"
echo "PHREEQC database: $PHREEQC_DB"

export PHREEQC_BIN
export PHREEQC_DB

echo "=== Running solver ==="
cd /app
python3 /solution/solver.py

echo "=== Done ==="
