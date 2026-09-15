#!/bin/bash

set -e

# Run the computational fix script
python3 /solution/fix_ftbfs.py

# Build the project
cd /app
rm -rf build
cmake -B build -S .
cmake --build build -j$(nproc)

# Verify binary runs
./build/sigframe
