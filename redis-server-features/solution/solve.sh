#!/bin/bash

set -e

# Generate corrected source files
python3 /solution/solve_impl.py

# Build the server
cd /app
make clean && make
