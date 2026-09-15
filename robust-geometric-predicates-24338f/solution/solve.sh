#!/usr/bin/env bash

set -e

# Replace the skeleton predicates.cpp with the complete solution
cp /solution/predicates_solution.cpp /app/predicates.cpp

# Build
cd /app
make clean
make

# Verify
./test_predicates
