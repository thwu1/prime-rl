#!/bin/bash

# Step 1: Build the C++ float tool
cp /solution/float_tool_impl.cpp /app/src/float_tool.cpp
cd /app
cmake -B build -DCMAKE_BUILD_TYPE=Release 2>&1
cmake --build build 2>&1

# Step 2: Run the Python solver to parse all data and generate audit.csv
python3 /solution/solver.py
