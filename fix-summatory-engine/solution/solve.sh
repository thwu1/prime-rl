#!/bin/bash

set -e

# Step 1: Fix engine.cpp and update CMakeLists.txt, build shared library
python3 /solution/fix_and_build.py

# Step 2: Create Python ctypes bindings
python3 /solution/create_bindings.py

# Step 3: Benchmark across optimization levels and write evaluation.json
python3 /solution/benchmark.py
