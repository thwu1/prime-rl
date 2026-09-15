#!/bin/bash

set -e

# Compile the CST analyzer against SDSL v3 headers
g++-14 -std=c++17 -O2 -I/opt/sdsl/include \
    -o /app/cst_analyzer /solution/analyzer.cpp -pthread

# Run the analyzer to produce /app/results.json
/app/cst_analyzer /app/results.json
