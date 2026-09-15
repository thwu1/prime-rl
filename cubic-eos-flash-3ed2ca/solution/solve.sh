#!/bin/bash

# Apply all fixes and implement stability analysis
python3 /solution/fix_and_implement.py

# Build and run
cd /app && cmake -B build && cmake --build build && ./build/flash_solver
