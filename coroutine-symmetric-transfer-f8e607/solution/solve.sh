#!/bin/bash

set -e

python3 /solution/apply_fixes.py

# Verify the fix compiles
cd /app
g++ -std=c++20 -I include -O2 -o example example.cpp
./example
echo "Solution applied and verified."
