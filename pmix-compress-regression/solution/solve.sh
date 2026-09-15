#!/bin/bash

# Apply all fixes using the helper script
python3 /solution/apply_fixes.py

# Rebuild from clean and verify
cd /app
make clean
make

# Run the test suite
./test_ppn
