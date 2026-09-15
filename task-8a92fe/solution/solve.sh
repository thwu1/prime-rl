#!/bin/bash

set -e

# Build the C++ pairing engine
cd /app/CPPDubovSystem
mkdir -p build
cd build
cmake .. 2>&1
make -j2 2>&1

# Verify the binary was built
if [ ! -f /app/CPPDubovSystem/build/CPPDubovSystem ]; then
    echo "ERROR: Engine binary not found after build"
    exit 1
fi

echo "Engine built successfully"

# Run the analysis Python script
cd /app
python3 /solution/analyze_tournament.py
