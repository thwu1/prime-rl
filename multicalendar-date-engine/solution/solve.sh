#!/bin/bash

# Apply all fixes
python3 /solution/fix_engine.py

# Build
cd /app
rm -rf build
mkdir -p build && cd build
cmake .. && cmake --build .
