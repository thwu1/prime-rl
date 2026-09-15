#!/bin/bash

set -u

pip3 install pytest==8.3.4 -q

# Build PHREEQC3 if not already built
PHREEQC_BIN=""
PHREEQC_DB=""

# Check if phreeqc binary already exists from solve step
PHREEQC_BIN=$(find /tmp -name "phreeqc" -type f -executable 2>/dev/null | head -1)
if [ -n "$PHREEQC_BIN" ]; then
    PHREEQC_DB=$(find /tmp -name "phreeqc.dat" -path "*/database/*" 2>/dev/null | head -1)
fi

# If not found, build from source
if [ -z "$PHREEQC_BIN" ] || [ -z "$PHREEQC_DB" ]; then
    echo "Building PHREEQC3 from source for test verification..."
    cd /tmp
    if [ ! -d "/tmp/phreeqc3-master" ]; then
        wget -q https://github.com/phreeqc-dev/phreeqc3/archive/refs/heads/master.tar.gz -O phreeqc3.tar.gz
        tar xzf phreeqc3.tar.gz --no-same-owner --no-same-permissions 2>/dev/null || true
        if [ ! -d "/tmp/phreeqc3-master" ]; then
            echo "ERROR: Failed to extract phreeqc3 source"
            mkdir -p /logs/verifier
            echo "0.0" > /logs/verifier/reward.txt
            exit 1
        fi
        rm -f phreeqc3.tar.gz
    fi
    cd phreeqc3-master
    mkdir -p _build && cd _build
    cmake .. -DCMAKE_BUILD_TYPE=Release > /dev/null 2>&1
    make -j$(nproc) > /dev/null 2>&1
    PHREEQC_BIN=$(find /tmp/phreeqc3-master/_build -name "phreeqc" -type f -executable 2>/dev/null | head -1)
    PHREEQC_DB=$(find /tmp/phreeqc3-master -name "phreeqc.dat" -path "*/database/*" 2>/dev/null | head -1)
fi

if [ -z "$PHREEQC_BIN" ] || [ -z "$PHREEQC_DB" ]; then
    echo "ERROR: Could not build or find PHREEQC binary"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

export PHREEQC_BIN
export PHREEQC_DB

echo "Using PHREEQC binary: $PHREEQC_BIN"
echo "Using database: $PHREEQC_DB"

cd /app

pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
