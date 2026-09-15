#!/bin/bash

cd /app

# Generate the compacting GC implementation
python3 /solution/solve_helper.py

# Build and verify with standard compilation
make clean && make && ./vm_test

# Verify clean under Valgrind
valgrind --leak-check=full --error-exitcode=99 ./vm_test
