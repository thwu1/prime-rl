#!/bin/bash


# Apply all fixes: implement stub functions, fix driver, fix cmake
python3 /solution/apply_fixes.py

# Clean build
cd /app
rm -rf build
mkdir -p build
cd build
cmake .. && make

# Run evaluation pipeline
cd /app
python3 driver.py
