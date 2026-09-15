#!/bin/bash

cd /app

# Apply all fixes to the broken header using computational patching
python3 /solution/fix_header.py

# Clean build to verify fixes
rm -rf build
mkdir -p build && cd build && cmake .. && make -j$(nproc) && ./test_runner
